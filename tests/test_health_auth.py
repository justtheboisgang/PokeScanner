"""Block 4: Health check (stiller Scanner faellt auf) + Passwortschutz."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.auth import _credentials_ok
from app.config import get_settings
from app.health import HEARTBEAT_SOURCE, WARNING_SOURCE, HealthMonitor
from app.main import create_app
from app.models.usage_event import UsageEvent

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


class _Notifier:
    def __init__(self):
        self.sent: list[str] = []

    def send_text(self, content: str) -> None:
        self.sent.append(content)


def _monitor(scoped_factory, notifier=None, **over):
    settings = get_settings().model_copy(update=over)
    return HealthMonitor(
        notifier or _Notifier(), session_factory=scoped_factory, settings=settings
    )


def _heartbeat(db, when: datetime, source: str = HEARTBEAT_SOURCE) -> None:
    db.add(UsageEvent(source=source, calls=1, recorded_at=when))
    db.commit()


def test_no_warning_while_polls_are_fresh(db, scoped_factory):
    _heartbeat(db, NOW - timedelta(minutes=20))
    notifier = _Notifier()
    monitor = _monitor(scoped_factory, notifier)
    assert monitor.is_stale(NOW) is False
    assert monitor.check(NOW) is False
    assert notifier.sent == []


def test_warns_after_silence_window(db, scoped_factory):
    _heartbeat(db, NOW - timedelta(hours=4))
    notifier = _Notifier()
    monitor = _monitor(scoped_factory, notifier)
    assert monitor.is_stale(NOW) is True
    assert monitor.check(NOW) is True
    assert len(notifier.sent) == 1
    assert "kein erfolgreicher Scan" in notifier.sent[0]


def test_warning_is_not_repeated_within_cooldown(db, scoped_factory):
    _heartbeat(db, NOW - timedelta(hours=4))
    notifier = _Notifier()
    monitor = _monitor(scoped_factory, notifier)

    assert monitor.check(NOW) is True
    # Still dead a minute later: no second message.
    assert monitor.check(NOW + timedelta(minutes=1)) is False
    assert len(notifier.sent) == 1

    # After the cooldown it warns again — the worker is still down.
    assert monitor.check(NOW + timedelta(hours=4)) is True
    assert len(notifier.sent) == 2


def test_never_polled_does_not_warn(db, scoped_factory):
    notifier = _Notifier()
    monitor = _monitor(scoped_factory, notifier)
    # Nothing to compare against yet (fresh install) — silence is not a failure.
    assert monitor.is_stale(NOW) is False
    assert monitor.check(NOW) is False


def test_disabled_health_check_never_warns(db, scoped_factory):
    _heartbeat(db, NOW - timedelta(days=2))
    notifier = _Notifier()
    monitor = _monitor(scoped_factory, notifier, health_check_enabled=False)
    assert monitor.check(NOW) is False
    assert notifier.sent == []


def test_poll_writes_a_heartbeat(db, scoped_factory):
    """An empty poll must still prove the scanner is alive."""
    from app.ingest.pipeline import IngestionPipeline, PollStats

    pipeline = IngestionPipeline(
        sources=[],
        notifier=_Notifier(),
        session_factory=scoped_factory,
        settings=get_settings().model_copy(update={"enrich_auto_value_enabled": False}),
    )
    pipeline._record_usage(PollStats())

    monitor = _monitor(scoped_factory)
    assert monitor.last_poll_at() is not None
    assert monitor.is_stale(datetime.now(timezone.utc)) is False


# --- Passwortschutz --------------------------------------------------------


def test_credentials_check():
    assert _credentials_ok("Basic " + _b64("poke:geheim"), "poke", "geheim") is True
    assert _credentials_ok("Basic " + _b64("poke:falsch"), "poke", "geheim") is False
    assert _credentials_ok("Basic " + _b64("wer:geheim"), "poke", "geheim") is False
    assert _credentials_ok(None, "poke", "geheim") is False
    assert _credentials_ok("Bearer abc", "poke", "geheim") is False
    assert _credentials_ok("Basic not-base64!!", "poke", "geheim") is False


def _b64(raw: str) -> str:
    return base64.b64encode(raw.encode()).decode()


@pytest.fixture()
def protected_client(session_factory, monkeypatch):
    from app.api.deps import get_db

    get_settings.cache_clear()
    monkeypatch.setenv("WEB_PASSWORD", "geheim")
    monkeypatch.setenv("WEB_USERNAME", "poke")
    app = create_app()

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_api_requires_password_when_set(protected_client):
    resp = protected_client.get("/api/candidates")
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"].startswith("Basic")


def test_api_accepts_correct_password(protected_client):
    resp = protected_client.get(
        "/api/candidates", headers={"Authorization": "Basic " + _b64("poke:geheim")}
    )
    assert resp.status_code == 200


def test_health_endpoint_stays_open(protected_client):
    # Monitoring/Compose must be able to probe without credentials.
    assert protected_client.get("/api/health").status_code == 200


def test_unprotected_by_default(client):
    # No WEB_PASSWORD in the test env: the API is open (local development).
    assert client.get("/api/candidates").status_code == 200
