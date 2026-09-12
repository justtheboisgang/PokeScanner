FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY . .

# Phase 1 has no web server yet. The default command applies migrations; the
# compose file keeps the container alive for `docker compose exec` work.
CMD ["alembic", "upgrade", "head"]
