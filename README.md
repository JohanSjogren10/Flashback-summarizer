# Flashback-summarizer

Summera huvudinnehållet i en godtycklig Flashback-tråd – utan att klicka dig
igenom ibland 100 sidor.

Appen hämtar alla sidor i en tråd, extraherar inläggens text och skapar en
sammanfattning (TL;DR + nyckelpunkter) på svenska. Sammanfattningen görs med en
map-reduce-strategi så att även mycket långa trådar kan hanteras.

## Funktioner

- **Scraping** av sidorna i en tråd (Flashback paginerar via `t<id>p<sida>`),
  med custom `User-Agent`, fördröjning mellan requests och en sidgräns.
- **Parallell hämtning**: upp till 4 sidor i taget med en gemensam
  takt-throttle, så att en tråd sammanfattas på sekunder i stället för
  minuter utan att belasta Flashback mer än tidigare.
- **Tål hastighetsbegränsning (429)**: nya försök med exponentiell backoff som
  respekterar `Retry-After`, automatiskt ökad fördröjning och delresultat i
  stället för ett kraschat jobb.
- **Urvalsstrategi för långa trådar**: `spread` (jämnt fördelat över hela
  tråden, standard), `first` eller `last`.
- **Sidcache** i minnet (15 min) så att omkörningar inte belastar Flashback.
- **Sammanfattning** med chunkning + map-reduce (chunkarna sammanfattas
  parallellt och antalet begränsas, så även jättetrådar går fort).
  - **LLM-motor** via valfri OpenAI-kompatibel tjänst (t.ex. Groq, OpenRouter
    eller Google Gemini – alla har gratisnivåer) när `LLM_API_KEY` är satt.
  - **Extraktiv fallback** utan externa API:er eller kostnad (fungerar offline,
    och används automatiskt om LLM-anropet misslyckas).
- **Enkelt webbgränssnitt**: klistra in URL och tryck **Sammanfatta**. Vill du
  finjustera längd, max antal sidor, urval eller fördröjning finns de under
  "Avancerat".

## Kom igång

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Kör webbservern
uvicorn app.main:app --reload
```

Öppna sedan http://127.0.0.1:8000 i webbläsaren.

### Aktivera LLM-sammanfattning (valfritt, gratisnivåer finns)

Appen pratar med vilken OpenAI-kompatibel chat-API som helst. Välj en
leverantör med gratisnivå och sätt tre miljövariabler:

| Leverantör | `LLM_BASE_URL` | Exempel på `LLM_MODEL` |
| --- | --- | --- |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| OpenRouter | `https://openrouter.ai/api/v1` | `meta-llama/llama-3.3-70b-instruct:free` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-2.0-flash` |
| OpenAI (betald) | *(lämna tom)* | `gpt-4o-mini` |

```bash
export LLM_API_KEY="din-nyckel"
export LLM_BASE_URL="https://api.groq.com/openai/v1"
export LLM_MODEL="llama-3.3-70b-versatile"
```

De äldre namnen `OPENAI_API_KEY`, `OPENAI_BASE_URL` och `OPENAI_MODEL` fungerar
fortfarande. Utan nyckel används den extraktiva fallbacken automatiskt, och
appen kostar då ingenting alls.

## Gratis webbsida (dela med vänner)

Appen kräver ingen databas och ingen betald tjänst. Rekommenderade
gratisalternativ (Hugging Face Spaces används inte längre eftersom en
Docker-Space kostar pengar):

### GitHub Pages (frontend) + Render/Koyeb (backend)

Vill du ha en länk av typen
`https://<användare>.github.io/Flashback-summarizer` publicerar
`.github/workflows/pages.yml` innehållet i `static/` som en Pages-sida.

GitHub Pages kan bara servera statiska filer, så själva scrapingen och
sammanfattningen måste köras på en backend (se Render/Koyeb nedan):

1. Driftsätt backend först (t.ex. på Render) och notera dess URL.
2. Aktivera Pages i repot: **Settings → Pages → Source: GitHub Actions**.
3. Lägg till repo-variabeln `API_BASE_URL` med backendens URL
   (**Settings → Secrets and variables → Actions → Variables**). Utan den kan
   besökaren i stället fylla i **Backend-URL** under "Avancerat" på sidan –
   värdet sparas i webbläsaren.
4. Kör workflowet (push till `main` eller **Actions → Run workflow**).

Backenden svarar med CORS-headers så att Pages-sidan får anropa den. Sätt
miljövariabeln `ALLOWED_ORIGINS` (kommaseparerad lista, t.ex.
`https://<användare>.github.io`) om du vill begränsa vilka sidor som får
anropa API:et; standard är alla.

### Render (enklast, gratisplan)

1. Skapa ett konto på https://render.com och välj **New → Blueprint**.
2. Peka det mot detta GitHub-repo. `render.yaml` i roten konfigurerar allt:
   gratisplan, Python 3.12, `pip install -r requirements.txt` och start med
   uvicorn på `$PORT`.
3. Din publika länk blir `https://<tjänstnamn>.onrender.com`.

Gratisinstanser somnar efter ~15 minuters inaktivitet; första anropet därefter
tar några sekunder extra. Hälsokontroll finns på `/api/health`.

### Koyeb (gratis nano-instans, sover inte)

1. Skapa ett konto på https://koyeb.com → **Create Web Service → GitHub**.
2. Välj **Buildpack** (läser `Procfile` och `runtime.txt`) eller **Dockerfile**.
3. Sätt hälsokontroll till `/api/health`. Porten läses från `PORT`.

### Andra Docker-värdar

`Dockerfile` är värd-agnostisk och lyssnar på `PORT` (standard `8000`), så
samma image kan köras på t.ex. Fly.io, Google Cloud Run eller en egen server:

```bash
docker build -t flashback-summarizer .
docker run -p 8000:8000 flashback-summarizer
```

> **Vill du använda LLM-motorn i molnet?** Sätt `LLM_API_KEY`, `LLM_BASE_URL`
> och `LLM_MODEL` som hemligheter hos din värd. Med en leverantörs gratisnivå
> förblir sidan gratis, men den kan bli hastighetsbegränsad – då faller appen
> automatiskt tillbaka på den extraktiva sammanfattaren.

## API

`POST /api/summarize`

Bara `url` är obligatoriskt – övriga fält har standardvärden
(`max_pages: 10`, `length: "medium"`, `delay: 0.5`, `strategy: "spread"`):

```json
{
  "url": "https://www.flashback.org/t1234567",
  "max_pages": 10,
  "length": "medium",
  "delay": 0.5,
  "strategy": "spread"
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
  "pages_fetched": 2,
  "total_pages": 300,
  "truncated": true,
  "notice": "Endast 2 av 300 sidor hämtades (urval: spread)."
}
```

`strategy` styr vilka sidor som hämtas när tråden har fler sidor än
`max_pages`: `spread` tar ett jämnt urval över hela tråden, `first` början och
`last` slutet (sida 1 hämtas alltid).

### Om `429 Too Many Requests`

Flashback stryper trafik från den som hämtar många sidor snabbt. Appen gör då
automatiskt nya försök (respekterar `Retry-After`), pausar alla parallella
hämtningar och ökar fördröjningen. Efter upprepade 429 hämtas sidorna en i
taget igen. Om begränsningen består returneras det som hann hämtas med
`truncated: true` och en förklarande `notice`. Höj `delay` (t.ex. 3–5 sekunder)
och/eller sänk `max_pages` för att slippa problemet i mycket långa trådar.

`GET /api/health` returnerar status, vilken backend som används och (om en
nyckel är satt) modell och bas-URL. Använd den som hälsokontroll hos din
värd.

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
