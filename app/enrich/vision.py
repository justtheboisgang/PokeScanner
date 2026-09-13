"""Vision triage via Claude (Phase 4, §10).

Advisory ONLY: the prompt forbids any buy/condition/authenticity decision and any
price. Output is a short German note for pre-sorting. Runs after the alarm, never
in the critical path.

The Anthropic client is injectable so this is testable without network/credentials.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import get_settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Du bist ein Vision-Triage-Assistent für Vintage-Pokémon-Karten. "
    "Beschreibe knapp (2-4 deutsche Sätze), was auf den Bildern zu sehen ist: "
    "erkennbare Ära/Serie, Sprache falls erkennbar, sichtbare Zustandshinweise. "
    "Nenne Auffälligkeiten, die eine genauere Prüfung nahelegen (z.B. Hinweise "
    "auf moderne Bulk-Ware statt Vintage oder mögliche Echtheits-Warnsignale). "
    "WICHTIG: Triff KEINE Kauf-, Zustands- oder Echtheitsentscheidung und nenne "
    "KEINEN Preis. Nur Hinweise zur Vorsortierung."
)


@dataclass(frozen=True)
class VisionResult:
    summary: str
    model: str


class VisionAnalyzer:
    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        enabled: bool | None = None,
        max_images: int | None = None,
        client=None,
    ) -> None:
        settings = get_settings()
        self.model = model or settings.enrich_vision_model
        self.max_images = (
            max_images if max_images is not None else settings.enrich_vision_max_images
        )
        self._enabled_flag = (
            settings.enrich_vision_enabled if enabled is None else enabled
        )
        self._client = client
        self._api_key = (
            api_key if api_key is not None else settings.anthropic_api_key
        )

    @property
    def enabled(self) -> bool:
        # Enabled if the flag is on AND we can obtain a client (injected, explicit
        # key, or an ambient credential the SDK can resolve).
        return self._enabled_flag and (
            self._client is not None or bool(self._api_key) or _has_ambient_credential()
        )

    def _get_client(self):
        if self._client is not None:
            return self._client
        import anthropic

        self._client = (
            anthropic.Anthropic(api_key=self._api_key)
            if self._api_key
            else anthropic.Anthropic()
        )
        return self._client

    def analyze(
        self, image_urls: list[str], *, title: str, description: str | None = None
    ) -> VisionResult | None:
        """Return an advisory triage note, or None if disabled/no images/failure."""
        if not self._enabled_flag or not image_urls:
            return None

        content: list[dict] = [
            {"type": "image", "source": {"type": "url", "url": url}}
            for url in image_urls[: self.max_images]
        ]
        listing_text = f"Titel: {title}"
        if description:
            listing_text += f"\nBeschreibung: {description}"
        content.append({"type": "text", "text": listing_text})

        try:
            client = self._get_client()
            resp = client.messages.create(
                model=self.model,
                max_tokens=500,
                system=_SYSTEM_PROMPT,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": content}],
            )
        except Exception:
            logger.exception("vision analysis failed")
            return None

        if getattr(resp, "stop_reason", None) == "refusal":
            logger.warning("vision analysis refused")
            return None

        summary = "".join(
            getattr(b, "text", "")
            for b in getattr(resp, "content", [])
            if getattr(b, "type", None) == "text"
        ).strip()
        if not summary:
            return None
        return VisionResult(summary=summary, model=self.model)


def _has_ambient_credential() -> bool:
    import os

    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
