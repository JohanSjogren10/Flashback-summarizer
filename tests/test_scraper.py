"""Tests for the Flashback scraper."""
from app.scraper import (
    detect_last_page,
    is_flashback_thread_url,
    parse_posts,
    parse_title,
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
