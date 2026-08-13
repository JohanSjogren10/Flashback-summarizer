# Flashback Summarizer – container image.
# Runs the free extractive backend by default (no LLM key = no cost).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static

# Most free Docker hosts (Koyeb, Render, Fly.io, Google Cloud Run) inject the
# port to listen on via PORT; 8000 is used when nothing is injected.
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
