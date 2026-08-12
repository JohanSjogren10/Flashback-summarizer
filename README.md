# Flashback-summarizer

Summera huvudinnehållet i en godtycklig Flashback-tråd – utan att klicka dig
igenom ibland 100 sidor.

Appen hämtar alla sidor i en tråd, extraherar inläggens text och skapar en
sammanfattning (TL;DR + nyckelpunkter) på svenska. Sammanfattningen görs med en
map-reduce-strategi så att även mycket långa trådar kan hanteras.

## Funktioner

- **Scraping** av alla sidor i en tråd (Flashback paginerar via `t<id>p<sida>`),
  med custom `User-Agent`, fördröjning mellan requests och en sidgräns.
- **Sammanfattning** med chunkning + map-reduce.
  - **LLM-motor** (OpenAI) när `OPENAI_API_KEY` är satt och `openai` är installerat.
  - **Extraktiv fallback** utan externa API:er eller kostnad (fungerar offline).
- **Enkelt webbgränssnitt**: klistra in URL, välj längd och max antal sidor.

## Kom igång

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Kör webbservern
uvicorn app.main:app --reload
```

Öppna sedan http://127.0.0.1:8000 i webbläsaren.

### Aktivera LLM-sammanfattning (valfritt)

```bash
pip install -r requirements-llm.txt
export OPENAI_API_KEY="din-nyckel"
export OPENAI_MODEL="gpt-4o-mini"   # valfritt
```

Utan API-nyckel används den extraktiva fallbacken automatiskt.

## Gratis webbsida (dela med vänner)

Appen kan köras helt gratis och publikt via **Hugging Face Spaces** (Docker).
Utan `OPENAI_API_KEY` används den kostnadsfria extraktiva sammanfattaren, så
det finns inga API-kostnader – oavsett hur många som använder sidan.

1. Skapa ett gratis konto på https://huggingface.co
2. Klicka **New Space** → välj **Docker** som SDK (tom mall).
3. Ladda upp projektets filer till Space:et (eller peka det mot detta
   GitHub-repo). `Dockerfile` i roten sköter bygget automatiskt.
4. Vänta tills bygget är klart – din publika länk blir
   `https://<användarnamn>-<space-namn>.hf.space`. Dela den med vänner.

`Dockerfile` lyssnar på porten i miljövariabeln `PORT` (standard `7860`, vilket
Hugging Face Spaces använder). Samma image fungerar även på andra gratis-Docker-
värdar som Render, Railway och Fly.io.

> **Vill du ändå använda OpenAI-motorn i molnet?** Sätt då `OPENAI_API_KEY` som
> en hemlighet i din Space. Observera att alla anrop då debiteras ditt eget
> OpenAI-konto. Lämna nyckeln osatt för att hålla sidan gratis.

## API

`POST /api/summarize`

```json
{
  "url": "https://www.flashback.org/t1234567",
  "max_pages": 20,
  "length": "medium",
  "delay": 1.0
}
```

Svar:

```json
{
  "url": "...",
  "title": "...",
  "tldr": "...",
  "bullets": ["...", "..."],
  "backend": "extractive",
  "num_posts": 42,
  "pages_fetched": 2
}
```

`GET /api/health` returnerar status och om en LLM-nyckel finns.

## Tester

```bash
pip install pytest
python -m pytest
```

## Att tänka på (etik & juridik)

- Var snäll mot servern: appen har fördröjning mellan sidhämtningar och en
  sidgräns som standard. Höj inte gränserna i onödan.
- Respektera Flashbacks användarvillkor och gällande lagstiftning. Använd
  sammanfattningar med källkritik – forumtext är inte verifierad fakta.
