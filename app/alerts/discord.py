"""Discord webhook notifier (§8).

Posts an embed with image, title, price, estimated profit, cascade level + sample
size, channel, link and the copy-ready contact message. Sending uses `wait=true`
so Discord returns the message id, which is stored so later enrichment can EDIT
the same embed instead of sending a second message (R1).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import httpx

from app.alerts.messages import contact_message
from app.config import get_settings

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
    ) -> None:
        self.webhook_url = (
            webhook_url if webhook_url is not None else get_settings().discord_webhook_url
        )
        self._client = httpx.Client(transport=transport, timeout=timeout)

    def __enter__(self) -> "DiscordNotifier":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def send(self, content: AlertContent) -> str | None:
        """Send an alert embed. Returns the Discord message id (for later edits)."""
        if not self.enabled:
            return None
        resp = self._client.post(
            self.webhook_url,
            params={"wait": "true"},
            # Suppress mention injection: listing titles are attacker-controlled,
            # so a title like "@everyone" must never ping.
            json={
                "embeds": [build_embed(content)],
                "allowed_mentions": {"parse": []},
            },
        )
        resp.raise_for_status()
        body = resp.json()
        message_id = body.get("id") if isinstance(body, dict) else None
        return str(message_id) if message_id is not None else None

    def edit(self, message_id: str, content: AlertContent) -> None:
        """Edit an existing alert embed in place (enrichment, R1). Phase 4."""
        if not self.enabled:
            return
        resp = self._client.patch(
            f"{self.webhook_url}/messages/{message_id}",
            json={
                "embeds": [build_embed(content)],
                "allowed_mentions": {"parse": []},
            },
        )
        resp.raise_for_status()
