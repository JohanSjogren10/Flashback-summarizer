"""Tests for the summarizer (extractive fallback)."""
from app.summarizer import Summarizer, chunk_text, split_sentences


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
