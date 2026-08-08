# Flashback Summarizer – container image.
# Runs the free extractive backend by default (no OPENAI_API_KEY = no cost).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static

# Hugging Face Spaces expects the app on port 7860; other hosts (Render,
# Railway, Fly) inject their own PORT which is honoured below.
EXPOSE 7860

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
