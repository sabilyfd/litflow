# ── base: shared Python env ───────────────────────────────────────────────────
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency manifest first for layer caching
COPY pyproject.toml .

# Sync all dependencies into .venv
RUN uv sync --no-dev

# Add virtualenv bin to PATH so gunicorn/celery are found
ENV PATH="/app/.venv/bin:$PATH"


# ── web: Flask + Gunicorn ─────────────────────────────────────────────────────
FROM base AS web

COPY web/ ./web/

EXPOSE 5000
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "web.app:app"]


# ── worker: Celery + Surya OCR ────────────────────────────────────────────────
FROM base AS worker

# System deps for pdf2image (poppler) — worker only
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY worker/ ./worker/

# Worker needs db.py to update job status in SQLite
COPY web/db.py ./web/db.py
RUN touch ./web/__init__.py

CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=info", "--concurrency=1"]
