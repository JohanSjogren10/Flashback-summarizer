"""Scraping utilities for Flashback threads.

Fetches pages of a thread, parses individual posts and returns cleaned text.
Designed to be polite to the server: configurable delay with jitter, adaptive
throttling and retries when the server answers ``429 Too Many Requests``, a
custom User-Agent, a small page cache and a hard cap on the number of pages.
"""
from __future__ import annotations

import email.utils
import random
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; FlashbackSummarizer/1.0; "
    "+https://github.com/JohanSjogren10/Flashback-summarizer)"
)

#: HTTP status codes that are worth retrying after a pause.
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

#: Upper bound for the adaptive delay between page requests (seconds).
MAX_DELAY = 15.0

#: Longest single backoff pause we are willing to wait (seconds).
MAX_BACKOFF = 60.0

#: How long a cached page stays fresh (seconds).
CACHE_TTL = 900.0

STRATEGIES = ("first", "spread", "last")

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
    #: Page numbers that were actually fetched, in the order they were read.
    pages: List[int] = field(default_factory=list)
    #: Total number of pages the thread has (as advertised by Flashback).
    total_pages: int = 1
    #: True when we did not read every page of the thread.
    truncated: bool = False
    #: Human readable explanation of *why* the thread was truncated.
    notice: Optional[str] = None

    @property
    def text(self) -> str:
        """All post texts joined into a single string."""
        return "\n\n".join(p.text for p in self.posts if p.text)

    @property
    def pages_fetched(self) -> int:
        return len(self.pages)


class ScrapeError(Exception):
    """Raised when a thread cannot be scraped."""


class RateLimitError(ScrapeError):
    """Raised when the server keeps answering ``429 Too Many Requests``."""


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


def select_pages(
    total_pages: int, max_pages: int, strategy: str = "spread"
) -> List[int]:
    """Pick which pages to fetch from a thread with *total_pages* pages.

    ``first`` reads the beginning of the thread, ``last`` the end and
    ``spread`` an evenly distributed sample across the whole thread. Page 1 is
    always included because it carries the title and the pagination links.
    """
    if strategy not in STRATEGIES:
        raise ScrapeError(
            "Okänd strategi: " + strategy + ". Välj 'first', 'spread' "
            "eller 'last'."
        )
    total_pages = max(1, total_pages)
    max_pages = max(1, max_pages)
    if total_pages <= max_pages:
        return list(range(1, total_pages + 1))

    if max_pages == 1:
        return [1]
    if strategy == "first":
        return list(range(1, max_pages + 1))
    if strategy == "last":
        pages = list(range(total_pages - max_pages + 2, total_pages + 1))
        return [1] + pages

    # "spread": page 1, the last page and an even sample in between.
    step = (total_pages - 1) / (max_pages - 1)
    pages = {1, total_pages}
    for index in range(1, max_pages - 1):
        pages.add(min(total_pages, 1 + round(index * step)))
    selected = sorted(pages)
    # Rounding can collapse duplicates; top up with unused pages nearby.
    if len(selected) < max_pages:
        for candidate in range(2, total_pages):
            if len(selected) >= max_pages:
                break
            if candidate not in pages:
                pages.add(candidate)
                selected = sorted(pages)
    return selected


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Parse a ``Retry-After`` header value into seconds.

    Supports both the delta-seconds and the HTTP-date form. Returns ``None``
    when the header is missing or unparsable.
    """
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    try:
        seconds = parsed.timestamp() - time.time()
    except (OverflowError, OSError, ValueError):  # pragma: no cover - guard
        return None
    return max(0.0, seconds)


class PageCache:
    """A tiny thread-safe in-memory cache of fetched pages."""

    def __init__(self, ttl: float = CACHE_TTL, max_entries: int = 512) -> None:
        self.ttl = ttl
        self.max_entries = max_entries
        self._entries: Dict[str, Tuple[float, str]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[str]:
        now = time.time()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            stored_at, html = entry
            if now - stored_at > self.ttl:
                self._entries.pop(key, None)
                return None
            return html

    def set(self, key: str, html: str) -> None:
        with self._lock:
            if len(self._entries) >= self.max_entries:
                oldest = min(
                    self._entries, key=lambda k: self._entries[k][0]
                )
                self._entries.pop(oldest, None)
            self._entries[key] = (time.time(), html)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


#: Process-wide cache, shared between requests so a re-run is cheap.
PAGE_CACHE = PageCache()


def _jittered(delay: float) -> float:
    """Add ±30 % jitter so the traffic pattern looks less robotic."""
    if delay <= 0:
        return 0.0
    return delay * random.uniform(0.7, 1.3)


def _build_client(user_agent: str, timeout: float) -> httpx.Client:
    headers = {
        "User-Agent": user_agent,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    kwargs = dict(headers=headers, timeout=timeout, follow_redirects=True)
    try:  # HTTP/2 needs the optional 'h2' package.
        return httpx.Client(http2=True, **kwargs)
    except ImportError:
        return httpx.Client(**kwargs)


class _Fetcher:
    """Fetches thread pages with caching, retries and adaptive throttling."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        delay: float,
        max_retries: int,
        cache: Optional[PageCache],
    ) -> None:
        self.client = client
        self.base_delay = max(0.0, delay)
        self.delay = self.base_delay
        self.max_retries = max(0, max_retries)
        self.cache = cache
        self.referer: Optional[str] = None
        self._successes = 0

    def wait_between_pages(self) -> None:
        if self.delay > 0:
            time.sleep(_jittered(self.delay))

    def _slow_down(self) -> None:
        self._successes = 0
        self.delay = min(MAX_DELAY, max(1.0, self.delay * 2))

    def _speed_up(self) -> None:
        self._successes += 1
        if self._successes >= 3 and self.delay > self.base_delay:
            self.delay = max(self.base_delay, self.delay * 0.75)
            self._successes = 0

    def get(self, url: str) -> str:
        if self.cache is not None:
            cached = self.cache.get(url)
            if cached is not None:
                return cached

        html = self._get_with_retries(url)
        self.referer = url
        if self.cache is not None:
            self.cache.set(url, html)
        return html

    def _get_with_retries(self, url: str) -> str:
        headers = {"Referer": self.referer} if self.referer else None
        last_status: Optional[int] = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                if attempt >= self.max_retries:
                    raise ScrapeError(
                        f"Kunde inte hämta {url}: {exc}"
                    ) from exc
                time.sleep(_jittered(self._backoff(attempt)))
                continue

            status = response.status_code
            if status < 400:
                self._speed_up()
                return response.text

            if status not in RETRY_STATUS_CODES:
                raise ScrapeError(
                    f"Kunde inte hämta {url}: servern svarade {status}."
                )

            last_status = status
            if status == 429:
                self._slow_down()
            if attempt >= self.max_retries:
                break
            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            if retry_after is not None:
                # Honour the server's instruction exactly; jitter could make
                # us retry sooner than allowed.
                time.sleep(min(MAX_BACKOFF, retry_after))
            else:
                time.sleep(_jittered(self._backoff(attempt)))

        message = (
            f"Flashback svarade {last_status} (för många förfrågningar) för "
            f"{url} även efter {self.max_retries} nya försök. Försök igen om "
            "en stund, minska antalet sidor eller öka fördröjningen."
        )
        raise RateLimitError(message)

    def _backoff(self, attempt: int) -> float:
        return min(MAX_BACKOFF, 5.0 * (2**attempt))


def scrape_thread(
    url: str,
    *,
    max_pages: int = 20,
    delay: float = 2.0,
    timeout: float = 20.0,
    user_agent: str = DEFAULT_USER_AGENT,
    client: Optional[httpx.Client] = None,
    strategy: str = "spread",
    max_retries: int = 4,
    cache: Optional[PageCache] = PAGE_CACHE,
) -> Thread:
    """Scrape a Flashback thread and return the parsed :class:`Thread`.

    Parameters
    ----------
    url:
        Any page URL of the thread.
    max_pages:
        Hard cap on the number of pages fetched (politeness / cost control).
    delay:
        Base number of seconds to wait between page requests. The delay grows
        automatically when the server rate limits us.
    timeout:
        Per-request timeout in seconds.
    user_agent:
        Value for the ``User-Agent`` header.
    client:
        Optional pre-built httpx client (used in tests).
    strategy:
        How to pick pages when the thread is longer than *max_pages*:
        ``first``, ``last`` or ``spread`` (an even sample of the thread).
    max_retries:
        Number of extra attempts per page when the server answers 429/5xx.
    cache:
        Page cache to use, or ``None`` to disable caching.

    Pages that cannot be fetched because of rate limiting do not fail the
    whole job: whatever was read is returned with ``truncated=True`` and a
    ``notice`` explaining what happened. Only a thread where no page at all
    could be read raises :class:`ScrapeError`.
    """
    if not is_flashback_thread_url(url):
        raise ScrapeError(
            "URL:en ser inte ut som en Flashback-tråd. "
            "Exempel: https://www.flashback.org/t1234567"
        )
    if max_pages < 1:
        raise ScrapeError("max_pages måste vara minst 1.")
    if strategy not in STRATEGIES:
        raise ScrapeError(
            f"Okänd strategi: {strategy}. Välj 'first', 'spread' eller 'last'."
        )

    thread_id = _thread_id(url)
    owns_client = client is None
    if client is None:
        client = _build_client(user_agent, timeout)

    fetcher = _Fetcher(
        client, delay=delay, max_retries=max_retries, cache=cache
    )
    thread = Thread(url=url, title=None)
    try:
        first_url = _page_url(url, thread_id, 1)
        html = fetcher.get(first_url)
        thread.title = parse_title(html)
        thread.posts.extend(parse_posts(html))
        thread.pages.append(1)

        thread.total_pages = detect_last_page(html)
        pages = select_pages(thread.total_pages, max_pages, strategy)
        for page in pages:
            if page == 1:
                continue
            fetcher.wait_between_pages()
            try:
                page_html = fetcher.get(_page_url(url, thread_id, page))
            except RateLimitError as exc:
                thread.notice = str(exc)
                break
            thread.posts.extend(parse_posts(page_html))
            thread.pages.append(page)
    finally:
        if owns_client:
            client.close()

    if not thread.posts:
        raise ScrapeError(
            "Kunde inte hitta några inlägg. Flashbacks markup kan ha ändrats "
            "eller så kräver tråden inloggning."
        )

    thread.truncated = thread.pages_fetched < thread.total_pages
    if thread.truncated and thread.notice is None:
        thread.notice = (
            f"Endast {thread.pages_fetched} av {thread.total_pages} sidor "
            f"hämtades (urval: {strategy})."
        )
    return thread
