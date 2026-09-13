"""Kleinanzeigen poll pipeline (Phase 2).

Orchestration only; the risky logic (price parsing, normalization, alarm rule,
embed building, API clients) lives in unit-tested modules. End-to-end runs need
Postgres (Listing uses JSONB/ARRAY).

Per item: upsert listing (dedup on channel+external_id) -> if newly seen and it
passes the cheap gate, create an unbewertbar candidate, send the Discord alert,
and record the message id. Every fetched listing is stored either way — abgelehnte
Listings sind Kalibrierungsdaten (§5).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.alerts.discord import AlertContent, DiscordNotifier
from app.clients.apify import ApifyClient
from app.clients.exceptions import QuotaExceededError
from app.config import Settings, get_settings
from app.config_data import SearchTerms, load_search_terms
from app.db import session_scope
from app.ingest.alarm import evaluate
from app.ingest.kleinanzeigen import build_run_input, normalize
from app.ingest.repo import create_candidate, mark_alert_sent, upsert_listing
from app.models.candidate import Candidate

logger = logging.getLogger(__name__)


@dataclass
class PollStats:
    queries: int = 0
    items_seen: int = 0
    new_listings: int = 0
    alerts_sent: int = 0
    skipped_seen: int = 0
    skipped_excluded: int = 0
    skipped_unparseable: int = 0
    errors: int = 0
    per_term_new: dict[str, int] = field(default_factory=dict)


class KleinanzeigenPipeline:
    def __init__(
        self,
        apify: ApifyClient,
        notifier: DiscordNotifier,
        *,
        session_factory: Callable[[], AbstractContextManager[Session]] = session_scope,
        settings: Settings | None = None,
        search_terms: SearchTerms | None = None,
    ) -> None:
        self.apify = apify
        self.notifier = notifier
        self.session_factory = session_factory
        self.settings = settings or get_settings()
        self.search_terms = search_terms or load_search_terms()

    def poll(self) -> PollStats:
        """Run one poll over the active query subset."""
        stats = PollStats()
        actor = self.settings.apify_kleinanzeigen_actor
        if not actor:
            logger.warning("APIFY_KLEINANZEIGEN_ACTOR not set; poll is a no-op")
            return stats

        for term in self.search_terms.active:
            stats.queries += 1
            try:
                items = self.apify.run_actor_get_items(
                    actor,
                    build_run_input(term),
                    max_items=self.settings.apify_max_items_per_query,
                )
            except QuotaExceededError:
                logger.error("Apify usage limit reached; stopping poll early")
                break
            except Exception:
                logger.exception("Apify run failed for term %r", term)
                stats.errors += 1
                continue

            for item in items:
                stats.items_seen += 1
                try:
                    self._process_item(item, term, stats)
                except Exception:
                    logger.exception("Failed to process item for term %r", term)
                    stats.errors += 1

        logger.info("poll done: %s", stats)
        return stats

    def _process_item(self, item: dict, term: str, stats: PollStats) -> None:
        normalized = normalize(item)
        if normalized is None:
            stats.skipped_unparseable += 1
            return

        candidate_id: int | None = None
        content: AlertContent | None = None

        with self.session_factory() as session:
            listing, is_new = upsert_listing(session, normalized)
            if not is_new:
                stats.skipped_seen += 1
                return

            stats.new_listings += 1
            decision = evaluate(
                normalized,
                search_terms=self.search_terms,
                price_ceiling=self.settings.alert_price_ceiling_eur,
                require_price=self.settings.alert_require_price,
            )
            if not decision.should_alert:
                stats.skipped_excluded += 1
                return

            candidate = create_candidate(
                session,
                listing,
                matched_search_term=term,
                alert_reason=decision.reason,
            )
            candidate_id = candidate.id
            content = AlertContent(
                title=normalized.title,
                url=normalized.url,
                price=normalized.price,
                currency=normalized.currency,
                location=normalized.location,
                channel="Kleinanzeigen",
                matched_search_term=term,
                image_url=(normalized.images[0] if normalized.images else None),
            )

        # Alert I/O outside the transaction (R1: alert is the critical path).
        message_id: str | None = None
        try:
            message_id = self.notifier.send(content)
        except Exception:
            logger.exception("Discord send failed for candidate %s", candidate_id)

        with self.session_factory() as session:
            candidate = session.get(Candidate, candidate_id)
            if candidate is not None:
                mark_alert_sent(session, candidate, message_id)
        stats.alerts_sent += 1
        stats.per_term_new[term] = stats.per_term_new.get(term, 0) + 1
