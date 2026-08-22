"""Tests for the summarizer (extractive fallback)."""
from app.summarizer import (
    MAX_LLM_CHUNKS,
    Summarizer,
    chunk_text,
    select_chunks,
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


def test_select_chunks_keeps_richest_chunks_in_order():
    chunks = ["kort", "en mycket längre bit text", "mellanlång text"]
    assert select_chunks(chunks, max_chunks=2) == [
        "en mycket längre bit text",
        "mellanlång text",
    ]
    # Nothing is dropped when the thread fits within the budget.
    assert select_chunks(chunks, max_chunks=5) == chunks


def test_select_chunks_caps_huge_threads():
    chunks = [f"Stycke {i}" for i in range(MAX_LLM_CHUNKS * 3)]
    assert len(select_chunks(chunks)) == MAX_LLM_CHUNKS


def test_llm_map_runs_in_parallel_and_respects_chunk_cap():
    calls = []

    class FakeSummarizer(Summarizer):
        def _llm_map(self, chunk):
            calls.append(chunk)
            return f"sammanfattning: {chunk[:10]}"

        def _llm_complete(self, prompt, *, max_tokens):
            return "TLDR: En sammanfattning.\n- Punkt ett\n- Punkt två"

    summarizer = FakeSummarizer(api_key=None, chunk_size=50)
    summarizer._llm = object()  # pretend a provider is configured
    text = "\n\n".join(f"Stycke nummer {i} med en del text." for i in range(60))
    result = summarizer.summarize(text, length="short")
    assert result.backend == "llm"
    assert result.tldr == "En sammanfattning."
    assert result.bullets == ["Punkt ett", "Punkt två"]
    assert 0 < len(calls) <= MAX_LLM_CHUNKS
