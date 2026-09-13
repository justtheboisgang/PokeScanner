"""Vision triage via Claude (Phase 4, §10).

Advisory ONLY: the prompt forbids any buy/condition/authenticity decision and any
price. Output is a short German note for pre-sorting. Runs after the alarm, never
in the critical path.

Images are downloaded here and sent as base64 (not as URLs): marketplace image
hosts often block or time out Anthropic's server-side fetch, so we fetch them
ourselves. The Anthropic client and the HTTP transport are injectable so this is
testable without network/credentials.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass

import httpx

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

# Anthropic accepts these image media types.
_ALLOWED_MEDIA = {"image/jpeg", "image/png", "image/gif", "image/webp"}


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
        http_transport: httpx.BaseTransport | None = None,
        http_timeout: float = 20.0,
        max_image_bytes: int = 5_000_000,
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
        self._api_key = api_key if api_key is not None else settings.anthropic_api_key
        self._http = httpx.Client(
            transport=http_transport, timeout=http_timeout, follow_redirects=True
        )
        self.max_image_bytes = max_image_bytes

    @property
    def enabled(self) -> bool:
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

    def _fetch_image_block(self, url: str) -> dict | None:
        """Download an image and return an Anthropic base64 image block, or None."""
        try:
            resp = self._http.get(url)
            resp.raise_for_status()
            data = resp.content
            if not data or len(data) > self.max_image_bytes:
                return None
            media = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            if media not in _ALLOWED_MEDIA:
                media = "image/jpeg"
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media,
                    "data": base64.standard_b64encode(data).decode("ascii"),
                },
            }
        except Exception:
            logger.info("vision image download failed for %s", url, exc_info=True)
            return None

    def analyze(
        self, image_urls: list[str], *, title: str, description: str | None = None
    ) -> VisionResult | None:
        """Return an advisory triage note, or None if disabled/no usable image/failure."""
        if not self._enabled_flag or not image_urls:
            return None

        content: list[dict] = []
        for url in image_urls[: self.max_images]:
            block = self._fetch_image_block(url)
            if block is not None:
                content.append(block)
        if not content:
            return None  # no image could be downloaded

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

    return bool(
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )
