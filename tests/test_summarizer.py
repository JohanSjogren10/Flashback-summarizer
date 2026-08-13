"""Tests for the summarizer (extractive fallback)."""
from app.summarizer import (
    Summarizer,
    chunk_text,
    llm_api_key,
    llm_base_url,
    llm_model,
    split_sentences,
)


def test_split_sentences():
    text = "Första meningen. Andra meningen! Tredje?"
    assert split_sentences(text) == [
        "Första meningen.",
        "Andra meningen!",
        "Tredje?",
    ]
    assert split_sentences("") == []


def test_chunk_text_respects_max_chars():
    paragraphs = "\n\n".join(f"Stycke nummer {i} med lite text." for i in range(20))
    chunks = chunk_text(paragraphs, max_chars=80)
    assert len(chunks) > 1
    assert all(len(c) <= 160 for c in chunks)


def test_chunk_text_hard_splits_large_paragraph():
    big = "a" * 500
    chunks = chunk_text(big, max_chars=100)
    assert len(chunks) == 5


def test_extractive_summary_produces_bullets():
    text = (
        "En man hittades död i sin lägenhet i Stockholm. "
        "Polisen misstänker mord och har inlett en förundersökning. "
        "Grannar hörde bråk kvällen innan. "
        "En misstänkt person har gripits av polisen. "
        "Mannen var i 40-årsåldern enligt uppgifter. "
        "Rättsläkare undersöker nu dödsorsaken noggrant."
    )
    summarizer = Summarizer(api_key=None)
    assert summarizer.backend == "extractive"
    result = summarizer.summarize(text, length="short", num_posts=6)
    assert result.tldr
    assert 1 <= len(result.bullets) <= 3
    assert result.backend == "extractive"
    assert result.num_posts == 6


def test_empty_text_returns_message():
    summarizer = Summarizer(api_key=None)
    result = summarizer.summarize("", length="medium")
    assert result.bullets == []
    assert "Ingen text" in result.tldr


def test_llm_config_prefers_provider_neutral_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "gammal")
    monkeypatch.setenv("LLM_API_KEY", "ny")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("LLM_MODEL", "llama-3.3-70b-versatile")
    assert llm_api_key() == "ny"
    assert llm_base_url() == "https://api.groq.com/openai/v1"
    assert llm_model() == "llama-3.3-70b-versatile"


def test_llm_config_falls_back_to_openai_env(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "gammal")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert llm_api_key() == "gammal"
    assert llm_base_url() is None
    assert llm_model() == "gpt-4o-mini"


def test_llm_failure_falls_back_to_extractive():
    text = (
        "En man hittades död i sin lägenhet i Stockholm. "
        "Polisen misstänker mord och har inlett en förundersökning. "
        "Grannar hörde bråk kvällen innan."
    )
    summarizer = Summarizer(api_key=None)
    # Simulate a configured provider whose calls all fail (rate limited, ...).
    summarizer._llm = object()
    summarizer._summarize_llm = lambda *args, **kwargs: ("", [])
    result = summarizer.summarize(text, length="short")
    assert result.backend == "extractive"
    assert result.tldr
    assert result.bullets
