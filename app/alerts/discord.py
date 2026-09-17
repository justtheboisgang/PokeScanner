"""Discord webhook notifier (§8).

Posts an embed with image, title, price, estimated profit, cascade level + sample
size, channel, link and the copy-ready contact message. Sending uses `wait=true`
so Discord returns the message id, which is stored so later enrichment can EDIT
the same embed instead of sending a second message (R1).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

import httpx

from app.alerts.messages import contact_message
from app.config import get_settings

logger = logging.getLogger(__name__)

# Discord embed color (a calm blue). Cosmetic only.
_EMBED_COLOR = 0x5865F2


@dataclass(frozen=True)
class AlertContent:
    title: str
    url: str | None
    price: Decimal | None
    currency: str
    location: str | None
    channel: str
    matched_search_term: str | None
    image_url: str | None
    # Enrichment fields — in Phase 2 these describe "unbewertbar".
    profit_text: str = "unbewertbar — bitte selbst prüfen"
    cascade_text: str = "—"
    # Phase 4 enrichment (advisory only, §10).
    condition_flags: tuple[str, ...] = ()
    vision_summary: str | None = None


def _price_text(price: Decimal | None, currency: str) -> str:
    if price is None:
        return "Preis unbekannt"
    if price == 0:
        return "Zu verschenken (0 €)"
    return f"{price:g} {currency}"


def build_embed(content: AlertContent) -> dict:
    fields = [
        {"name": "💶 Preis", "value": _price_text(content.price, content.currency), "inline": True},
        {"name": "📈 Gesch. Gewinn", "value": content.profit_text, "inline": True},
        {"name": "🪜 Kaskade / Sample", "value": content.cascade_text, "inline": True},
        {"name": "📍 Ort", "value": content.location or "—", "inline": True},
        {"name": "🛒 Kanal", "value": content.channel, "inline": True},
        {
            "name": "🔎 Suchbegriff",
            "value": content.matched_search_term or "—",
            "inline": True,
        },
    ]
    if content.condition_flags:
        fields.append(
            {
                "name": "⚠️ Zustandshinweise (Text)",
                "value": ", ".join(content.condition_flags),
                "inline": False,
            }
        )
    if content.vision_summary:
        fields.append(
            {
                "name": "👁️ Vision-Triage (Hinweis, keine Bewertung)",
                "value": content.vision_summary[:1024],
                "inline": False,
            }
        )
    fields.append(
        {
            "name": "📋 Kontaktnachricht (kopieren)",
            "value": f"```{contact_message()}```",
            "inline": False,
        }
    )
    embed: dict = {
        "title": content.title[:256],
        "color": _EMBED_COLOR,
        "fields": fields,
    }
    if content.url:
        embed["url"] = content.url
    if content.image_url:
        embed["image"] = {"url": content.image_url}
    return embed


class DiscordNotifier:
    def __init__(
        self,
        webhook_url: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
        min_interval: float | None = None,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        settings = get_settings()
        self.webhook_url = (
            webhook_url if webhook_url is not None else settings.discord_webhook_url
        )
        self._client = httpx.Client(transport=transport, timeout=timeout)
        # Discord rate-limits webhooks hard. Space requests out so we rarely hit
        # 429 at all, and honour Retry-After when we still do (§8).
        self._min_interval = (
            settings.discord_min_interval_seconds
            if min_interval is None
            else min_interval
        )
        self._max_retries = max_retries
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None

    def _throttle(self) -> None:
        if self._min_interval <= 0 or self._last_request_at is None:
            return
        wait = self._min_interval - (self._monotonic() - self._last_request_at)
        if wait > 0:
            self._sleep(wait)

    @staticmethod
    def _retry_after(resp: httpx.Response) -> float:
        """Seconds Discord asks us to wait. Body wins; it is the precise one."""
        try:
            body = resp.json()
            if isinstance(body, dict) and body.get("retry_after") is not None:
                return max(0.0, float(body["retry_after"]))
        except (ValueError, TypeError):
            pass
        header = resp.headers.get("Retry-After")
        if header is not None:
            try:
                return max(0.0, float(header))
            except ValueError:
                pass
        return 1.0

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Send one request, waiting out 429s instead of dropping the alert."""
        for attempt in range(self._max_retries + 1):
            self._throttle()
            try:
                resp = self._client.request(method, url, **kwargs)
            finally:
                self._last_request_at = self._monotonic()
            if resp.status_code != 429:
                resp.raise_for_status()
                return resp
            if attempt == self._max_retries:
                resp.raise_for_status()
            wait = self._retry_after(resp)
            logger.warning(
                "Discord rate limited, waiting %.2fs (attempt %d/%d)",
                wait,
                attempt + 1,
                self._max_retries,
            )
            self._sleep(wait)
        raise RuntimeError("unreachable")

    def __enter__(self) -> "DiscordNotifier":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def send_text(self, content: str) -> None:
        """Post a plain text message (operational warnings, not listing alerts)."""
        if not self.enabled:
            return
        self._request(
            "POST",
            self.webhook_url,
            json={"content": content[:2000], "allowed_mentions": {"parse": []}},
        )

    def send(self, content: AlertContent) -> str | None:
        """Send an alert embed. Returns the Discord message id (for later edits)."""
        if not self.enabled:
            return None
        resp = self._request(
            "POST",
            self.webhook_url,
            params={"wait": "true"},
            # Suppress mention injection: listing titles are attacker-controlled,
            # so a title like "@everyone" must never ping.
            json={
                "embeds": [build_embed(content)],
                "allowed_mentions": {"parse": []},
            },
        )
        body = resp.json()
        message_id = body.get("id") if isinstance(body, dict) else None
        return str(message_id) if message_id is not None else None

    def edit(self, message_id: str, content: AlertContent) -> None:
        """Edit an existing alert embed in place (enrichment, R1). Phase 4."""
        if not self.enabled:
            return
        self._request(
            "PATCH",
            f"{self.webhook_url}/messages/{message_id}",
            json={
                "embeds": [build_embed(content)],
                "allowed_mentions": {"parse": []},
            },
        )
