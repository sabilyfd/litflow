# ── base: shared Python env ───────────────────────────────────────────────────
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Create a non-root user and group
RUN groupadd -g 1000 appuser && useradd -u 1000 -g appuser -d /app -s /bin/sh appuser

# Copy dependency manifest first for layer caching
COPY pyproject.toml .

# Sync all dependencies into .venv
RUN uv sync --no-dev

# Add virtualenv bin to PATH so gunicorn/celery are found
ENV PATH="/app/.venv/bin:$PATH"

# Set ownership of /app to appuser
RUN chown -R appuser:appuser /app


# ── web: Flask + Gunicorn ─────────────────────────────────────────────────────
FROM base AS web

# su-exec: tiny helper to drop privileges after chown-ing /jobs as root
RUN apt-get update && apt-get install -y --no-install-recommends su-exec \
    && rm -rf /var/lib/apt/lists/*

COPY web/ ./web/
COPY docker/web-entrypoint.sh /usr/local/bin/web-entrypoint.sh
RUN chown -R appuser:appuser /app/web \
    && chmod +x /usr/local/bin/web-entrypoint.sh

# Stay as root so the entrypoint can chown /jobs, then drops to appuser
EXPOSE 5000
ENTRYPOINT ["web-entrypoint.sh"]
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "web.app:app"]


# ── worker: Celery + Surya OCR ────────────────────────────────────────────────
FROM base AS worker

# System deps for pdf2image (poppler) — worker only
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY worker/ ./worker/
COPY web/db.py ./web/db.py
RUN touch ./web/__init__.py

RUN chown -R appuser:appuser /app/worker /app/web

# Create jobs dir and set ownership
RUN mkdir -p /jobs && chown -R appuser:appuser /jobs

USER appuser

CMD ["sh", "-c", "celery -A worker.celery_app worker --loglevel=info --concurrency=${WORKER_CONCURRENCY:-1}"]
