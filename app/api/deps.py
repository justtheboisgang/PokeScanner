"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.db import get_sessionmaker


def get_db() -> Iterator[Session]:
    """Yield a DB session per request. Overridden in tests."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
