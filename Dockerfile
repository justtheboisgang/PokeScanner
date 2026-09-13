FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy the whole project first — installing the package needs the `app/` source.
COPY . .
RUN pip install --upgrade pip && pip install .

# Default command applies migrations; compose overrides it per service.
CMD ["alembic", "upgrade", "head"]
