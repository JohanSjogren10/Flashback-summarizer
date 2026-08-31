"""Tests for the FastAPI endpoints."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import allowed_origins, app
from app.scraper import DEFAULT_DELAY, DEFAULT_MAX_PAGES, Post, Thread

client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["backend"] in ("llm", "extractive")


def test_summarize_rejects_invalid_url():
    response = client.post("/api/summarize", json={"url": "https://example.com/x"})
    assert response.status_code == 422


def test_summarize_happy_path():
    fake_thread = Thread(
        url="https://www.flashback.org/t123",
        title="Ett svenskt mord",
        posts=[
            Post(author="A", date=None, text="En man hittades död i Stockholm."),
            Post(author="B", date=None, text="Polisen misstänker mord och utreder."),
        ],
        pages=[1, 2],
        total_pages=2,
    )
    with patch("app.main.scrape_thread", return_value=fake_thread):
        response = client.post(
            "/api/summarize",
            json={"url": "https://www.flashback.org/t123", "length": "short"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Ett svenskt mord"
    assert data["num_posts"] == 2
    assert data["tldr"]
    assert data["backend"] == "extractive"
    assert data["pages_fetched"] == 2
    assert data["total_pages"] == 2
    assert data["truncated"] is False
    assert data["notice"] is None


def test_summarize_reports_truncated_thread():
    fake_thread = Thread(
        url="https://www.flashback.org/t123",
        title="Lång tråd",
        posts=[Post(author="A", date=None, text="Ett inlägg om en händelse.")],
        pages=[1],
        total_pages=300,
        truncated=True,
        notice="Endast 1 av 300 sidor hämtades (urval: spread).",
    )
    with patch("app.main.scrape_thread", return_value=fake_thread):
        response = client.post(
            "/api/summarize",
            json={"url": "https://www.flashback.org/t123", "strategy": "spread"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["truncated"] is True
    assert data["total_pages"] == 300
    assert "300 sidor" in data["notice"]


def test_summarize_rejects_unknown_strategy():
    response = client.post(
        "/api/summarize",
        json={"url": "https://www.flashback.org/t123", "strategy": "random"},
    )
    assert response.status_code == 422


def test_index_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "Flashback Summarizer" in response.text


def test_summarize_uses_defaults_when_only_url_is_given():
    fake_thread = Thread(
        url="https://www.flashback.org/t123",
        title="Tråd",
        posts=[Post(author="A", date=None, text="Ett inlägg om en händelse.")],
        pages=[1],
        total_pages=1,
    )
    with patch("app.main.scrape_thread", return_value=fake_thread) as scrape:
        response = client.post(
            "/api/summarize",
            json={"url": "https://www.flashback.org/t123"},
        )
    assert response.status_code == 200
    kwargs = scrape.call_args.kwargs
    assert kwargs["max_pages"] == DEFAULT_MAX_PAGES
    assert kwargs["delay"] == DEFAULT_DELAY
    assert kwargs["strategy"] == "spread"


def test_summarize_still_accepts_explicit_settings():
    fake_thread = Thread(
        url="https://www.flashback.org/t123",
        title="Tråd",
        posts=[Post(author="A", date=None, text="Ett inlägg om en händelse.")],
        pages=[1],
        total_pages=1,
    )
    with patch("app.main.scrape_thread", return_value=fake_thread) as scrape:
        response = client.post(
            "/api/summarize",
            json={
                "url": "https://www.flashback.org/t123",
                "max_pages": 3,
                "delay": 4.5,
                "strategy": "last",
            },
        )
    assert response.status_code == 200
    kwargs = scrape.call_args.kwargs
    assert kwargs["max_pages"] == 3
    assert kwargs["delay"] == 4.5
    assert kwargs["strategy"] == "last"


def test_health_allows_cross_origin_requests():
    response = client.get(
        "/api/health", headers={"Origin": "https://example.github.io"}
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_allowed_origins_can_be_restricted(monkeypatch):
    monkeypatch.setenv(
        "ALLOWED_ORIGINS", "https://example.github.io, https://other.example"
    )
    assert allowed_origins() == [
        "https://example.github.io",
        "https://other.example",
    ]


def test_allowed_origins_defaults_to_any(monkeypatch):
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    assert allowed_origins() == ["*"]
