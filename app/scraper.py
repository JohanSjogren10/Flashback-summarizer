"""Scraping utilities for Flashback threads.

Fetches all pages of a thread, parses individual posts and returns cleaned
text. Designed to be polite to the server (configurable delay, custom
User-Agent, and a hard cap on the number of pages).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; FlashbackSummarizer/1.0; "
    "+https://github.com/JohanSjogren10/Flashback-summarizer)"
)

# Flashback thread URLs look like:
#   https://www.flashback.org/t1234567
#   https://www.flashback.org/t1234567p42   (page 42)
_THREAD_RE = re.compile(r"/t(\d+)(?:p(\d+))?", re.IGNORECASE)


@dataclass
class Post:
    """A single forum post."""

    author: Optional[str]
    date: Optional[str]
    text: str


@dataclass
class Thread:
    """A parsed Flashback thread."""

    url: str
    title: Optional[str]
    posts: List[Post] = field(default_factory=list)

    @property
    def text(self) -> str:
        """All post texts joined into a single string."""
        return "\n\n".join(p.text for p in self.posts if p.text)


class ScrapeError(Exception):
    """Raised when a thread cannot be scraped."""


def is_flashback_thread_url(url: str) -> bool:
    """Return True if *url* looks like a Flashback thread URL."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.netloc or "").lower()
    if not (host == "flashback.org" or host.endswith(".flashback.org")):
        return False
    return _THREAD_RE.search(parsed.path or "") is not None


def _thread_id(url: str) -> str:
    match = _THREAD_RE.search(urlparse(url).path or "")
    if not match:
        raise ScrapeError(f"Inte en giltig Flashback-tråd-URL: {url}")
    return match.group(1)


def _page_url(base_url: str, thread_id: str, page: int) -> str:
    """Build the URL for a specific page of a thread."""
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    if page <= 1:
        return urljoin(root, f"/t{thread_id}")
    return urljoin(root, f"/t{thread_id}p{page}")


def clean_text(text: str) -> str:
    """Collapse whitespace and trim a block of text."""
    text = text.replace("\xa0", " ")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines).strip()


def parse_posts(html: str) -> List[Post]:
    """Parse the posts out of a Flashback thread page.

    The parser tries a few selectors to stay robust against markup changes.
    Quotes, signatures and script/style noise are removed from each post.
    """
    soup = BeautifulSoup(html, "html.parser")
    posts: List[Post] = []

    # Candidate containers, most specific first.
    containers = soup.select("div.post_message") or soup.select(
        "div.post-message"
    )
    if not containers:
        # Fall back to whole post blocks and dig for the message body.
        blocks = soup.select("div.post") or soup.select("table.post")
        for block in blocks:
            body = (
                block.select_one(".post_message")
                or block.select_one(".post-message")
                or block.select_one(".content")
                or block
            )
            post = _build_post(block, body)
            if post and post.text:
                posts.append(post)
        return posts

    for body in containers:
        # Try to find an enclosing block for author/date metadata.
        block = body.find_parent(
            lambda tag: tag.name in ("div", "table")
            and "post" in " ".join(tag.get("class", []))
        )
        post = _build_post(block, body)
        if post and post.text:
            posts.append(post)
    return posts


def _build_post(block, body) -> Optional[Post]:
    if body is None:
        return None

    # Work on a copy so we don't mutate the shared soup tree.
    body = body.__copy__()

    # Remove noise: quoted text, signatures, scripts, styles.
    for selector in (
        "script",
        "style",
        "div.quote",
        "div.bbcode_quote",
        "blockquote",
        "div.signature",
        ".post_signature",
        ".signature",
    ):
        for tag in body.select(selector):
            tag.decompose()

    text = clean_text(body.get_text("\n"))
    if not text:
        return None

    author = None
    date = None
    if block is not None:
        author_tag = (
            block.select_one("a.post-user-username")
            or block.select_one(".post_author")
            or block.select_one("a.bigusername")
        )
        if author_tag:
            author = author_tag.get_text(strip=True) or None
        date_tag = block.select_one(".post-date") or block.select_one(
            ".post_date"
        )
        if date_tag:
            date = clean_text(date_tag.get_text(" ")) or None

    return Post(author=author, date=date, text=text)


def parse_title(html: str) -> Optional[str]:
    """Extract the thread title from a page."""
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("h1")
    if heading:
        title = heading.get_text(strip=True)
        if title:
            return title
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return None


def detect_last_page(html: str) -> int:
    """Return the highest page number referenced in the pagination links."""
    soup = BeautifulSoup(html, "html.parser")
    max_page = 1
    for link in soup.find_all("a", href=True):
        match = re.search(r"/t\d+p(\d+)", link["href"])
        if match:
            max_page = max(max_page, int(match.group(1)))
    return max_page


def scrape_thread(
    url: str,
    *,
    max_pages: int = 20,
    delay: float = 1.0,
    timeout: float = 20.0,
    user_agent: str = DEFAULT_USER_AGENT,
    client: Optional[httpx.Client] = None,
) -> Thread:
    """Scrape a Flashback thread and return the parsed :class:`Thread`.

    Parameters
    ----------
    url:
        Any page URL of the thread.
    max_pages:
        Hard cap on the number of pages fetched (politeness / cost control).
    delay:
        Seconds to sleep between page requests.
    timeout:
        Per-request timeout in seconds.
    user_agent:
        Value for the ``User-Agent`` header.
    client:
        Optional pre-built httpx client (used in tests).
    """
    if not is_flashback_thread_url(url):
        raise ScrapeError(
            "URL:en ser inte ut som en Flashback-tråd. "
            "Exempel: https://www.flashback.org/t1234567"
        )
    if max_pages < 1:
        raise ScrapeError("max_pages måste vara minst 1.")

    thread_id = _thread_id(url)
    owns_client = client is None
    if client is None:
        client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout,
            follow_redirects=True,
        )

    thread = Thread(url=url, title=None)
    try:
        first_url = _page_url(url, thread_id, 1)
        html = _get(client, first_url)
        thread.title = parse_title(html)
        thread.posts.extend(parse_posts(html))

        last_page = min(detect_last_page(html), max_pages)
        for page in range(2, last_page + 1):
            if delay > 0:
                time.sleep(delay)
            page_html = _get(client, _page_url(url, thread_id, page))
            thread.posts.extend(parse_posts(page_html))
    finally:
        if owns_client:
            client.close()

    if not thread.posts:
        raise ScrapeError(
            "Kunde inte hitta några inlägg. Flashbacks markup kan ha ändrats "
            "eller så kräver tråden inloggning."
        )
    return thread


def _get(client: httpx.Client, url: str) -> str:
    try:
        response = client.get(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:  # pragma: no cover - network errors
        raise ScrapeError(f"Kunde inte hämta {url}: {exc}") from exc
    return response.text
