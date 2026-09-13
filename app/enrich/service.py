"""EnrichmentService (Phase 4): text extraction + vision, edits the embed.

Runs after the alarm. Text extraction always runs; vision runs only when the
caller allows it (per-poll budget) and the listing has images. Results are
persisted and the existing Discord embed is edited in place (R1, §8).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.alerts.discord import AlertContent, DiscordNotifier
from app.db import session_scope
from app.enrich.text_extract import extract_condition_flags
from app.enrich.vision import VisionAnalyzer
from app.models.candidate import Candidate
from app.models.enrichment import Enrichment

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentOutcome:
    condition_flags: list[str]
    vision_used: bool


def _build_content(candidate: Candidate, flags: list[str], vision_summary: str | None) -> AlertContent:
    listing = candidate.listing
    rv = candidate.reference_value
    if rv is not None:
        cascade_text = f"Stufe {rv.cascade_level} · n={rv.sample_size}"
        profit_text = (
            f"+{candidate.estimated_profit}"
            if candidate.estimated_profit is not None
            else "unbewertbar — bitte selbst prüfen"
        )
    else:
        cascade_text = "—"
        profit_text = "unbewertbar — bitte selbst prüfen"
    return AlertContent(
        title=listing.title,
        url=listing.url,
        price=listing.price,
        currency=listing.currency,
        location=listing.location,
        channel="Kleinanzeigen",
        matched_search_term=candidate.matched_search_term,
        image_url=(listing.images[0] if listing.images else None),
        profit_text=profit_text,
        cascade_text=cascade_text,
        condition_flags=tuple(flags),
        vision_summary=vision_summary,
    )


class EnrichmentService:
    def __init__(
        self,
        vision: VisionAnalyzer,
        notifier: DiscordNotifier,
        *,
        session_factory: Callable[[], AbstractContextManager[Session]] = session_scope,
    ) -> None:
        self.vision = vision
        self.notifier = notifier
        self.session_factory = session_factory

    def enrich(self, candidate_id: int, *, allow_vision: bool) -> EnrichmentOutcome:
        content: AlertContent | None = None
        message_id: str | None = None
        flags: list[str] = []
        vision_used = False

        with self.session_factory() as session:
            candidate = session.scalars(
                select(Candidate)
                .where(Candidate.id == candidate_id)
                .options(
                    joinedload(Candidate.listing),
                    joinedload(Candidate.reference_value),
                    joinedload(Candidate.enrichment),
                )
            ).unique().one_or_none()
            if candidate is None:
                logger.warning("enrich: candidate %s not found", candidate_id)
                return EnrichmentOutcome([], False)

            listing = candidate.listing
            flags = extract_condition_flags(listing.title, listing.description)

            vision_summary: str | None = None
            vision_model: str | None = None
            if allow_vision and self.vision.enabled and listing.images:
                result = self.vision.analyze(
                    list(listing.images),
                    title=listing.title,
                    description=listing.description,
                )
                if result is not None:
                    vision_summary = result.summary
                    vision_model = result.model
                    vision_used = True

            enrichment = candidate.enrichment or Enrichment(candidate_id=candidate.id)
            enrichment.condition_flags = flags
            enrichment.vision_summary = vision_summary
            enrichment.vision_model = vision_model
            enrichment.vision_used = vision_used
            if enrichment.id is None:
                session.add(enrichment)

            message_id = candidate.discord_message_id
            content = _build_content(candidate, flags, vision_summary)

        # Edit the embed outside the transaction.
        if message_id and content is not None:
            try:
                self.notifier.edit(message_id, content)
            except Exception:
                logger.exception("failed to edit discord embed for candidate %s", candidate_id)

        return EnrichmentOutcome(flags, vision_used)
