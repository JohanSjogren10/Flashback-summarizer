"""FastAPI application for the Flashback thread summarizer."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .scraper import (
    STRATEGIES,
    ScrapeError,
    is_flashback_thread_url,
    scrape_thread,
)
from .summarizer import Summarizer, llm_api_key, llm_base_url, llm_model

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(
    title="Flashback Summarizer",
    description="Summera en Flashback-tråd utan att klicka igenom alla sidor.",
    version="1.0.0",
)


class SummarizeRequest(BaseModel):
    url: str = Field(..., description="URL till Flashback-tråden.")
    max_pages: int = Field(
        20, ge=1, le=200, description="Max antal sidor att hämta."
    )
    length: str = Field(
        "medium", description="Längd på sammanfattningen: short/medium/long."
    )
    delay: float = Field(
        2.0, ge=0.0, le=60.0, description="Fördröjning mellan sidor (sek)."
    )
    strategy: str = Field(
        "spread",
        description=(
            "Vilka sidor som väljs i långa trådar: first/spread/last."
        ),
    )


class SummarizeResponse(BaseModel):
    url: str
    title: Optional[str]
    tldr: str
    bullets: List[str]
    backend: str
    num_posts: int
    pages_fetched: int
    total_pages: int
    truncated: bool
    notice: Optional[str] = None


@app.post("/api/summarize", response_model=SummarizeResponse)
def summarize(request: SummarizeRequest) -> SummarizeResponse:
    if request.length not in ("short", "medium", "long"):
        raise HTTPException(
            status_code=422,
            detail="length måste vara 'short', 'medium' eller 'long'.",
        )
    if request.strategy not in STRATEGIES:
        raise HTTPException(
            status_code=422,
            detail="strategy måste vara 'first', 'spread' eller 'last'.",
        )
    if not is_flashback_thread_url(request.url):
        raise HTTPException(
            status_code=422,
            detail=(
                "Ogiltig URL. Ange en Flashback-tråd, t.ex. "
                "https://www.flashback.org/t1234567"
            ),
        )

    try:
        thread = scrape_thread(
            request.url,
            max_pages=request.max_pages,
            delay=request.delay,
            strategy=request.strategy,
        )
    except ScrapeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    summarizer = Summarizer()
    pages = thread.pages_fetched
    result = summarizer.summarize(
        thread.text,
        length=request.length,
        num_posts=len(thread.posts),
        num_pages_estimate=pages,
    )

    return SummarizeResponse(
        url=thread.url,
        title=thread.title,
        tldr=result.tldr,
        bullets=result.bullets,
        backend=result.backend,
        num_posts=len(thread.posts),
        pages_fetched=pages,
        total_pages=thread.total_pages,
        truncated=thread.truncated,
        notice=thread.notice,
    )


@app.get("/api/health")
def health() -> dict:
    has_key = bool(llm_api_key())
    return {
        "status": "ok",
        "llm": has_key,
        "backend": "llm" if has_key else "extractive",
        "model": llm_model() if has_key else None,
        "base_url": llm_base_url() if has_key else None,
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


if not STATIC_DIR.exists():
    raise RuntimeError(
        f"Static-katalogen saknas: {STATIC_DIR}. "
        "Kontrollera att 'static/' finns i projektet."
    )

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
