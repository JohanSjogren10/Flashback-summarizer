"""Tests for the FastAPI endpoints."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.scraper import Post, Thread

client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


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


def test_index_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "Flashback Summarizer" in response.text
