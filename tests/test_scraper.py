"""Tests for the Flashback scraper."""
from typing import List

import httpx
import pytest

from app import scraper
from app.scraper import (
    RateLimitError,
    detect_last_page,
    is_flashback_thread_url,
    parse_posts,
    parse_retry_after,
    parse_title,
    scrape_thread,
    select_pages,
)

SAMPLE_HTML = """
<html>
  <head><title>Ett svenskt mord - Flashback Forum</title></head>
  <body>
    <h1>Ett svenskt mord</h1>
    <div class="post">
      <a class="post-user-username">AnvändareA</a>
      <span class="post-date">2024-01-01, 12:00</span>
      <div class="post_message">
        Detta är det första inlägget om ett mord.
        <div class="bbcode_quote">Citat som ska tas bort</div>
        <div class="signature">Min signatur</div>
      </div>
    </div>
    <div class="post">
      <a class="post-user-username">AnvändareB</a>
      <span class="post-date">2024-01-02, 13:00</span>
      <div class="post_message">
        Här kommer ett andra inlägg med mer information.
        <script>var x = 1;</script>
      </div>
    </div>
    <div class="pagination">
      <a href="/t123p2">2</a>
      <a href="/t123p5">5</a>
    </div>
  </body>
</html>
"""


def test_is_flashback_thread_url():
    assert is_flashback_thread_url("https://www.flashback.org/t1234567")
    assert is_flashback_thread_url("https://flashback.org/t1234567p42")
    assert not is_flashback_thread_url("https://example.com/t123")
    assert not is_flashback_thread_url("https://www.flashback.org/forum")
    assert not is_flashback_thread_url("not a url")
    # Guard against look-alike domains.
    assert not is_flashback_thread_url("https://flashback.org.evil.com/t1")


def test_parse_posts_extracts_text_and_metadata():
    posts = parse_posts(SAMPLE_HTML)
    assert len(posts) == 2
    assert posts[0].author == "AnvändareA"
    assert "första inlägget" in posts[0].text
    # Quotes and signatures are removed.
    assert "Citat som ska tas bort" not in posts[0].text
    assert "Min signatur" not in posts[0].text
    # Scripts are removed.
    assert "var x" not in posts[1].text


def test_parse_title():
    assert parse_title(SAMPLE_HTML) == "Ett svenskt mord"


def test_detect_last_page():
    assert detect_last_page(SAMPLE_HTML) == 5
    assert detect_last_page("<html></html>") == 1


def _page_html(page: int, total: int = 5) -> str:
    links = "".join(f'<a href="/t123p{n}">{n}</a>' for n in range(2, total + 1))
    return f"""
    <html><head><title>Tråd</title></head><body>
      <h1>Tråd</h1>
      <div class="post">
        <div class="post_message">Inlägg på sida {page}.</div>
      </div>
      <div class="pagination">{links}</div>
    </body></html>
    """


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Make tests fast and record how long the scraper wanted to wait."""
    slept: List[float] = []
    monkeypatch.setattr(scraper.time, "sleep", slept.append)
    monkeypatch.setattr(scraper.random, "uniform", lambda a, b: 1.0)
    return slept


@pytest.fixture(autouse=True)
def _clear_cache():
    scraper.PAGE_CACHE.clear()
    yield
    scraper.PAGE_CACHE.clear()


def _client(handler) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://www.flashback.org",
    )


def test_select_pages_spread_samples_whole_thread():
    assert select_pages(300, 5, "spread") == [1, 76, 151, 225, 300]
    assert select_pages(300, 3, "first") == [1, 2, 3]
    assert select_pages(300, 3, "last") == [1, 299, 300]
    # Short threads are read in full regardless of strategy.
    assert select_pages(3, 10, "spread") == [1, 2, 3]
    # A single page budget only ever reads the first page.
    assert select_pages(300, 1, "spread") == [1]
    assert select_pages(300, 1, "last") == [1]


def test_parse_retry_after():
    assert parse_retry_after("30") == 30.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("inte ett datum") is None
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


def test_retries_after_429_and_succeeds(_no_sleep):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, text=_page_html(1, total=1))

    thread = scrape_thread(
        "https://www.flashback.org/t123",
        client=_client(handler),
        delay=0,
        cache=None,
    )
    assert calls["n"] == 2
    assert thread.posts
    assert not thread.truncated
    # Retry-After is respected instead of the default backoff.
    assert _no_sleep == [7.0]


def test_permanent_429_returns_partial_result():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/t123":
            return httpx.Response(200, text=_page_html(1, total=5))
        return httpx.Response(429)

    thread = scrape_thread(
        "https://www.flashback.org/t123",
        client=_client(handler),
        delay=0,
        max_retries=1,
        cache=None,
    )
    assert thread.pages == [1]
    assert thread.total_pages == 5
    assert thread.truncated
    assert "429" in (thread.notice or "")


def test_rate_limited_first_page_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    with pytest.raises(RateLimitError):
        scrape_thread(
            "https://www.flashback.org/t123",
            client=_client(handler),
            delay=0,
            max_retries=1,
            cache=None,
        )


def test_pages_are_cached_between_runs():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, text=_page_html(1, total=1))

    cache = scraper.PageCache()
    for _ in range(2):
        scrape_thread(
            "https://www.flashback.org/t123",
            client=_client(handler),
            delay=0,
            cache=cache,
        )
    assert calls["n"] == 1


def test_delay_grows_after_rate_limit(_no_sleep):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/t123":
            return httpx.Response(200, text=_page_html(1, total=3))
        if request.url.path == "/t123p2":
            return httpx.Response(429)
        return httpx.Response(200, text=_page_html(3, total=3))

    thread = scrape_thread(
        "https://www.flashback.org/t123",
        client=_client(handler),
        delay=1.0,
        max_retries=1,
        strategy="first",
        cache=None,
    )
    # Page 2 is rate limited, so scraping stops there with a partial result.
    assert thread.pages == [1]
    assert thread.truncated
