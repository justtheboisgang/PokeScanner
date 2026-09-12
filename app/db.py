"""SQLAlchemy engine, session factory and declarative base.

The engine is created lazily so that importing the ORM models (which only need
`Base`) never requires a database driver or a live connection — pure-logic code
and tests import cleanly without Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def make_engine(url: str | None = None) -> Engine:
    settings = get_settings()
    return create_engine(url or settings.database_url, pool_pre_ping=True, future=True)


@lru_cache
def get_engine() -> Engine:
    return make_engine()


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session scope."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
