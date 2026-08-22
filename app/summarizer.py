"""Summarization of long Flashback threads.

Uses a map-reduce strategy so that even very long threads (100+ pages) can be
summarized: the text is split into chunks, each chunk is summarized, and the
chunk summaries are combined into a final summary.

Two backends are supported:

* An LLM backend that talks to any OpenAI-compatible chat API. It is used when
  ``LLM_API_KEY`` (or the legacy ``OPENAI_API_KEY``) is set and the ``openai``
  package is installed. Several providers offer free tiers, e.g. Groq,
  OpenRouter and Google Gemini – point ``LLM_BASE_URL`` at the provider.
* A dependency-free extractive fallback that scores sentences by word
  frequency. This keeps the app usable offline and without API costs.
"""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, List, Optional

# Common Swedish stop words used by the extractive fallback.
_STOPWORDS = {
    "och", "att", "det", "som", "en", "på", "är", "för", "med", "av", "den",
    "inte", "om", "har", "de", "ett", "till", "jag", "så", "man", "men",
    "var", "eller", "vad", "kan", "han", "hon", "vi", "här", "där", "från",
    "när", "ska", "skulle", "hade", "blir", "bli", "vara", "sig", "sin",
    "sitt", "sina", "mer", "mycket", "också", "efter", "nu", "då", "ju",
    "väl", "mot", "under", "över", "utan", "genom", "detta", "dessa",
    "denna", "vid", "samt", "alla", "andra", "någon", "något", "några",
}

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[\wåäöÅÄÖ]+", re.UNICODE)

DEFAULT_LLM_MODEL = "gpt-4o-mini"

#: Largest number of chunks sent to the LLM. Huge threads would otherwise turn
#: into dozens of API calls; the most content-rich chunks are used instead.
MAX_LLM_CHUNKS = 12

#: How many chunk summaries to request in parallel.
LLM_CONCURRENCY = 4


def llm_api_key() -> Optional[str]:
    """Return the configured LLM API key, if any.

    ``LLM_API_KEY`` is the provider-neutral name; ``OPENAI_API_KEY`` is kept
    for backwards compatibility.
    """
    return os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")


def llm_base_url() -> Optional[str]:
    """Return the OpenAI-compatible base URL, if a custom one is configured.

    Free-tier examples:

    * Groq: ``https://api.groq.com/openai/v1``
    * OpenRouter: ``https://openrouter.ai/api/v1``
    * Google Gemini: ``https://generativelanguage.googleapis.com/v1beta/openai``
    """
    return os.environ.get("LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")


def llm_model() -> str:
    """Return the configured chat model name."""
    return (
        os.environ.get("LLM_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or DEFAULT_LLM_MODEL
    )


@dataclass
class SummaryResult:
    """Result of summarizing a thread."""

    tldr: str
    bullets: List[str]
    backend: str
    num_posts: int
    num_pages_estimate: int


def split_sentences(text: str) -> List[str]:
    """Split *text* into sentences (best effort)."""
    text = text.strip()
    if not text:
        return []
    parts = _SENTENCE_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def chunk_text(text: str, max_chars: int = 6000) -> List[str]:
    """Split *text* into chunks no larger than *max_chars* characters.

    Splits on paragraph boundaries where possible so chunks stay coherent.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0
    for para in paragraphs:
        para_len = len(para) + 2
        if current and current_len + para_len > max_chars:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        if para_len > max_chars:
            # Paragraph itself too large: hard-split it.
            for i in range(0, len(para), max_chars):
                chunks.append(para[i : i + max_chars])
            continue
        current.append(para)
        current_len += para_len
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def select_chunks(
    chunks: List[str], max_chunks: int = MAX_LLM_CHUNKS
) -> List[str]:
    """Keep at most *max_chunks* of the most content-rich chunks.

    Chunks are ranked by length (a proxy for how much substance they carry)
    and returned in their original order so the thread still reads
    chronologically.
    """
    if max_chunks < 1:
        raise ValueError("max_chunks must be positive")
    if len(chunks) <= max_chunks:
        return chunks
    ranked = sorted(
        range(len(chunks)), key=lambda i: len(chunks[i]), reverse=True
    )
    keep = sorted(ranked[:max_chunks])
    return [chunks[i] for i in keep]


def _extractive_summary(text: str, max_sentences: int) -> List[str]:
    """Return the *max_sentences* most representative sentences from *text*."""
    sentences = split_sentences(text)
    if len(sentences) <= max_sentences:
        return sentences

    # Word frequency scoring (ignoring stop words).
    freqs: dict[str, int] = {}
    for word in _WORD_RE.findall(text.lower()):
        if word in _STOPWORDS or len(word) <= 2:
            continue
        freqs[word] = freqs.get(word, 0) + 1
    if not freqs:
        return sentences[:max_sentences]

    max_freq = max(freqs.values())
    scored: List[tuple[float, int, str]] = []
    for index, sentence in enumerate(sentences):
        words = _WORD_RE.findall(sentence.lower())
        if not words:
            continue
        score = sum(freqs.get(w, 0) for w in words) / max_freq
        score /= len(words) ** 0.5  # dampen very long sentences
        scored.append((score, index, sentence))

    scored.sort(key=lambda item: item[0], reverse=True)
    top = scored[:max_sentences]
    # Preserve original order for readability.
    top.sort(key=lambda item: item[1])
    return [sentence for _, _, sentence in top]


class Summarizer:
    """Summarize threads using an LLM when available, else extractive."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        chunk_size: int = 6000,
    ) -> None:
        self.api_key = api_key or llm_api_key()
        self.model = model or llm_model()
        self.base_url = base_url or llm_base_url()
        self.chunk_size = chunk_size
        self._llm = self._init_llm()

    @property
    def backend(self) -> str:
        return "llm" if self._llm is not None else "extractive"

    def _init_llm(self):
        if not self.api_key:
            return None
        try:
            from openai import OpenAI
        except ImportError:
            return None
        try:
            if self.base_url:
                return OpenAI(api_key=self.api_key, base_url=self.base_url)
            return OpenAI(api_key=self.api_key)
        except Exception:  # pragma: no cover - defensive
            return None

    def summarize(
        self,
        text: str,
        *,
        length: str = "medium",
        num_posts: int = 0,
        num_pages_estimate: int = 0,
    ) -> SummaryResult:
        """Summarize *text* into a TL;DR and a list of bullet points."""
        bullet_target = {"short": 3, "medium": 6, "long": 10}.get(length, 6)

        if not text.strip():
            return SummaryResult(
                tldr="Ingen text kunde extraheras ur tråden.",
                bullets=[],
                backend=self.backend,
                num_posts=num_posts,
                num_pages_estimate=num_pages_estimate,
            )

        if self._llm is not None:
            tldr, bullets = self._summarize_llm(text, bullet_target)
            backend = "llm"
            if not tldr or not bullets:
                # The provider failed or returned an unusable answer (rate
                # limit, outage, ...): free tiers are best effort, so degrade
                # gracefully instead of returning an empty summary.
                tldr, bullets = self._summarize_extractive(text, bullet_target)
                backend = "extractive"
        else:
            tldr, bullets = self._summarize_extractive(text, bullet_target)
            backend = "extractive"

        return SummaryResult(
            tldr=tldr,
            bullets=bullets,
            backend=backend,
            num_posts=num_posts,
            num_pages_estimate=num_pages_estimate,
        )

    # -- Extractive backend -------------------------------------------------
    def _summarize_extractive(
        self, text: str, bullet_target: int
    ) -> tuple[str, List[str]]:
        chunks = chunk_text(text, self.chunk_size)
        # Map: pull key sentences from each chunk.
        collected: List[str] = []
        per_chunk = max(2, bullet_target // max(1, len(chunks)) + 1)
        for chunk in chunks:
            collected.extend(_extractive_summary(chunk, per_chunk))
        combined = " ".join(collected)
        # Reduce: pick the final bullets from the collected sentences.
        bullets = _extractive_summary(combined, bullet_target)
        tldr_sentences = _extractive_summary(combined, 2)
        tldr = " ".join(tldr_sentences) if tldr_sentences else combined[:280]
        return tldr, bullets

    # -- LLM backend --------------------------------------------------------
    def _summarize_llm(
        self, text: str, bullet_target: int
    ) -> tuple[str, List[str]]:
        chunks = select_chunks(chunk_text(text, self.chunk_size))
        chunk_summaries = self._llm_map_all(chunks)
        combined = "\n\n".join(s for s in chunk_summaries if s)
        return self._llm_reduce(combined, bullet_target)

    def _llm_map_all(self, chunks: List[str]) -> List[str]:
        """Summarize every chunk, a few requests at a time."""
        if len(chunks) <= 1:
            return [self._llm_map(chunk) for chunk in chunks]
        workers = min(LLM_CONCURRENCY, len(chunks))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(self._llm_map, chunks))

    def _llm_map(self, chunk: str) -> str:
        prompt = (
            "Sammanfatta följande utdrag från en Flashback-tråd på svenska. "
            "Fokusera på fakta, händelser och centrala påståenden. Var kortfattad.\n\n"
            f"{chunk}"
        )
        return self._llm_complete(prompt, max_tokens=400)

    def _llm_reduce(
        self, combined: str, bullet_target: int
    ) -> tuple[str, List[str]]:
        prompt = (
            "Nedan följer delsammanfattningar av en Flashback-tråd. "
            "Skapa en slutlig sammanfattning på svenska.\n"
            "Svara i exakt detta format:\n"
            "TLDR: <en till två meningar>\n"
            f"PUNKTER:\n- <punkt 1>\n- <punkt 2>\n(max {bullet_target} punkter)\n\n"
            f"{combined}"
        )
        response = self._llm_complete(prompt, max_tokens=700)
        return _parse_llm_response(response, bullet_target)

    def _llm_complete(self, prompt: str, *, max_tokens: int) -> str:
        try:
            completion = self._llm.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.3,
            )
            return (completion.choices[0].message.content or "").strip()
        except Exception:  # pragma: no cover - network/runtime errors
            return ""


def _parse_llm_response(
    response: str, bullet_target: int
) -> tuple[str, List[str]]:
    tldr = ""
    bullets: List[str] = []
    for raw_line in response.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("TLDR"):
            tldr = line.split(":", 1)[-1].strip()
        elif line.startswith(("-", "*", "•")):
            bullets.append(line.lstrip("-*• ").strip())
    if not tldr and response:
        response_sentences = split_sentences(response)
        tldr = response_sentences[0] if response_sentences else response[:280]
    return tldr, bullets[:bullet_target]
