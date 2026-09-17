"""Konfigurations-Check (Betrieb): maskiert Geheimnisse, luegt nicht gruen."""

from __future__ import annotations

from app.checkconfig import mask, report
from app.config import get_settings


def _settings(**over):
    return get_settings().model_copy(update=over)


def test_mask_never_reveals_the_secret():
    secret = "sc_live_abcdefghijklmnop"
    masked = mask(secret)
    assert secret not in masked
    assert masked.startswith("sc_")
    assert str(len(secret)) in masked


def test_mask_handles_empty():
    assert mask("") == "(leer)"


def test_not_ok_without_any_source(capsys):
    ok = report(_settings(apify_token="", ebay_browse_enabled=False,
                          willhaben_enabled=False, discord_webhook_url="https://x"))
    out = capsys.readouterr().out
    assert ok is False
    assert "Keine Quelle aktiv" in out


def test_kleinanzeigen_without_token_is_not_reported_as_running(capsys):
    """Ein gruener Haken ohne Token waere eine Luege."""
    report(_settings(kleinanzeigen_enabled=True, apify_token="",
                     discord_webhook_url="https://x"))
    out = capsys.readouterr().out
    assert "APIFY_TOKEN fehlt" in out


def test_not_ok_without_discord(capsys):
    ok = report(_settings(apify_token="tok", discord_webhook_url=""))
    out = capsys.readouterr().out
    assert ok is False
    assert "kein Alarm" in out


def test_ok_but_warns_when_soldcomps_missing(capsys):
    ok = report(_settings(apify_token="tok", discord_webhook_url="https://x",
                          soldcomps_api_key=""))
    out = capsys.readouterr().out
    assert ok is True
    assert "NICHT bewertet" in out
    assert ".env" in out  # weist auf die richtige Datei hin


def test_secrets_never_printed_in_full(capsys):
    token = "apify_api_SUPERGEHEIM123456"
    webhook = "https://discord.com/api/webhooks/999/GEHEIM"
    report(_settings(apify_token=token, discord_webhook_url=webhook,
                     soldcomps_api_key="sc_GEHEIM_KEY_1234"))
    out = capsys.readouterr().out
    assert token not in out
    assert webhook not in out
    assert "sc_GEHEIM_KEY_1234" not in out
