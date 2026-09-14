"""Ingestion pipeline (Phase 5): channel-agnostic poll over sources.

Per item: upsert listing (dedup on channel+external_id) -> if newly seen and it
passes the cheap gate, image-hash for cross-channel dedup, then (unless it's a
cross-posted duplicate) create an unbewertbar candidate, send the alert, record
the message id, and enrich. Every fetched listing is stored either way (§5).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.alerts.discord import AlertContent, DiscordNotifier
from app.clients.exceptions import QuotaExceededError
from app.config import Settings, get_settings
from app.config_data import SearchTerms, load_search_terms
from app.costs import PROVIDER_APIFY, CostGuard
from app.db import session_scope
from app.clients.tcgdex import TCGdexClient
from app.enrich.service import EnrichmentService
from app.enrich.vision import VisionAnalyzer
from app.ingest.alarm import evaluate
from app.ingest.dedup import ImageHasher, find_duplicate_listing
from app.ingest.normalized import NormalizedListing
from app.ingest.repo import (
    add_triggering_term,
    create_candidate,
    mark_alert_sent,
    upsert_listing,
)
from app.ingest.sources import Source, build_sources
from app.models.candidate import Candidate
from app.models.enums import Channel
from app.models.listing import Listing
from app.models.usage_event import UsageEvent

logger = logging.getLogger(__name__)

_CHANNEL_LABELS = {
    Channel.KLEINANZEIGEN: "Kleinanzeigen",
    Channel.WILLHABEN: "willhaben",
    Channel.EBAY_BROWSE: "eBay",
}

# Which cost-guard provider a channel bills against (eBay Browse is free -> None).
_CHANNEL_PROVIDER = {
    Channel.KLEINANZEIGEN: PROVIDER_APIFY,
    Channel.WILLHABEN: PROVIDER_APIFY,
    Channel.EBAY_BROWSE: None,
}


@dataclass
class PollStats:
    queries: int = 0
    items_seen: int = 0
    new_listings: int = 0
    alerts_sent: int = 0
    skipped_seen: int = 0
    skipped_excluded: int = 0
    skipped_unparseable: int = 0
    deduped: int = 0
    vision_calls: int = 0
    errors: int = 0
    per_term_new: dict[str, int] = field(default_factory=dict)
    per_source_queries: dict[str, int] = field(default_factory=dict)


class IngestionPipeline:
    def __init__(
        self,
        sources: list[Source],
        notifier: DiscordNotifier,
        *,
        session_factory: Callable[[], AbstractContextManager[Session]] = session_scope,
        settings: Settings | None = None,
        search_terms: SearchTerms | None = None,
        enrichment: EnrichmentService | None = None,
        hasher: ImageHasher | None = None,
        cost_guard: CostGuard | None = None,
    ) -> None:
        self.sources = sources
        self.notifier = notifier
        self.session_factory = session_factory
        self.settings = settings or get_settings()
        self.search_terms = search_terms or load_search_terms()
        self.cost_guard = cost_guard or CostGuard(
            session_factory=session_factory, settings=self.settings
        )
        self.enrichment = enrichment or EnrichmentService(
            VisionAnalyzer(),
            notifier,
            session_factory=session_factory,
            auto_valuer=self._build_auto_valuer(),
        )
        self._hasher = hasher
        self._vision_calls_left = 0

    def _build_auto_valuer(self):
        """Auto valuation callback for enrichment (Block 2.2), or None if off."""
        if not self.settings.enrich_auto_value_enabled:
            return None
        # Import here to keep the pricing layer out of the module import cycle.
        from app.models.candidate import Candidate as _Candidate
        from app.models.enums import Language
        from app.pricing.evaluate import auto_value_candidate
        from app.pricing.resolver import SingleCardTitleResolver

        lang = Language.DE if self.settings.tcgdex_primary_lang == "de" else Language.EN
        resolver = SingleCardTitleResolver(TCGdexClient(), lang=lang)

        def _valuer(session: Session, candidate: "_Candidate") -> object:
            return auto_value_candidate(
                session, candidate, resolver=resolver, settings=self.settings
            )

        return _valuer

    @property
    def hasher(self) -> ImageHasher | None:
        if not self.settings.dedup_image_hash_enabled:
            return None
        if self._hasher is None:
            self._hasher = ImageHasher()
        return self._hasher

    def poll(self) -> PollStats:
        """Run one poll over every source x active query term."""
        stats = PollStats()
        self._vision_calls_left = self.settings.enrich_vision_max_per_poll
        if not self.sources:
            logger.warning("no sources configured; poll is a no-op")
            return stats
        for source in self.sources:
            self._poll_source(source, stats)
        self._record_usage(stats)
        logger.info("poll done: %s", stats)
        return stats

    def _record_usage(self, stats: PollStats) -> None:
        """Persist real call counts per source for the Kosten view (§9)."""
        rows = dict(stats.per_source_queries)
        if stats.vision_calls:
            rows["vision"] = stats.vision_calls
        if not rows:
            return
        try:
            with self.session_factory() as session:
                for source, calls in rows.items():
                    session.add(UsageEvent(source=source, calls=calls))
        except Exception:
            logger.exception("failed to record usage")

    def _cost_provider(self, source: Source) -> str | None:
        return _CHANNEL_PROVIDER.get(source.channel)

    def _warn_provider_disabled(self, provider: str) -> None:
        if self.cost_guard.already_notified_today(provider):
            return
        spent = self.cost_guard.spent_today(provider)
        budget = self.cost_guard.budget(provider)
        try:
            self.notifier.send_text(
                f"⚠️ PokeScanner: Tagesbudget für **{provider}** erreicht "
                f"({spent:.2f} € / {budget:.2f} €). Der Provider ist für heute "
                f"deaktiviert; der Scan läuft ohne ihn weiter."
            )
        except Exception:
            logger.exception("failed to send budget warning for %s", provider)
        self.cost_guard.mark_notified(provider)

    def _poll_source(self, source: Source, stats: PollStats) -> None:
        provider = self._cost_provider(source)
        for term in self.search_terms.active:
            # Cost guard: skip this provider for the rest of the day if over budget.
            if provider is not None and self.cost_guard.is_disabled(provider):
                self._warn_provider_disabled(provider)
                logger.warning(
                    "provider %s over budget — skipping source %s", provider, source.name
                )
                return

            stats.queries += 1
            stats.per_source_queries[source.name] = (
                stats.per_source_queries.get(source.name, 0) + 1
            )
            try:
                listings = source.fetch(term)
            except QuotaExceededError:
                logger.error(
                    "quota reached for source %s; stopping it this poll", source.name
                )
                return
            except Exception:
                logger.exception("source %s failed for term %r", source.name, term)
                stats.errors += 1
                continue

            # Record estimated cost of this call (lexis bills per listing).
            if provider is not None:
                self.cost_guard.record(provider, source.name, units=len(listings))

            for normalized in listings:
                stats.items_seen += 1
                try:
                    self._process_item(normalized, term, stats)
                except Exception:
                    logger.exception(
                        "failed to process item from %s for term %r", source.name, term
                    )
                    stats.errors += 1

    def _process_item(
        self, normalized: NormalizedListing, term: str, stats: PollStats
    ) -> None:
        with self.session_factory() as session:
            listing, is_new = upsert_listing(session, normalized)
            listing_id = listing.id
            if not is_new:
                # Same ad surfaced by another active term — record that term (§1.1).
                add_triggering_term(session, listing_id, term)
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

        # Cross-channel dedup: hash the first image (I/O outside the transaction).
        image_hash: str | None = None
        if self.hasher is not None and normalized.images:
            image_hash = self.hasher.hash_url(normalized.images[0])

        candidate_id: int | None = None
        content: AlertContent | None = None
        with self.session_factory() as session:
            listing = session.get(Listing, listing_id)
            if listing is None:
                return
            if image_hash is not None:
                listing.image_hash = image_hash
                duplicate = find_duplicate_listing(
                    session,
                    image_hash=image_hash,
                    price=normalized.price,
                    exclude_listing_id=listing_id,
                    price_tolerance=self.settings.dedup_price_tolerance_eur,
                    hamming_threshold=self.settings.dedup_hamming_threshold,
                    hamming_lookback=self.settings.dedup_hamming_lookback,
                )
                if duplicate is not None:
                    stats.deduped += 1
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
                channel=_CHANNEL_LABELS.get(normalized.channel, normalized.channel.value),
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

        # Enrichment runs AFTER the alert (never in the critical path, §10).
        allow_vision = self._vision_calls_left > 0
        try:
            outcome = self.enrichment.enrich(candidate_id, allow_vision=allow_vision)
            if outcome.vision_used:
                self._vision_calls_left -= 1
                stats.vision_calls += 1
        except Exception:
            logger.exception("enrichment failed for candidate %s", candidate_id)


def build_pipeline(
    notifier: DiscordNotifier | None = None,
    *,
    settings: Settings | None = None,
) -> IngestionPipeline:
    """Construct the default pipeline with all enabled sources."""
    settings = settings or get_settings()
    notifier = notifier or DiscordNotifier()
    return IngestionPipeline(build_sources(settings), notifier, settings=settings)
