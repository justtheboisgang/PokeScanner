"""Sourcing channels (Phase 5).

A Source turns a search term into normalized listings for one channel. The
pipeline iterates sources x active terms; ingestion, dedup, alarm and enrichment
are shared downstream.
"""

from __future__ import annotations

import logging
from typing import Protocol

from app.clients.apify import ApifyClient
from app.clients.ebay import EbayBrowseClient
from app.config import Settings, get_settings
from app.ingest.ebay_browse import normalize_ebay_item
from app.ingest.kleinanzeigen import build_run_input, normalize_apify_item
from app.ingest.normalized import NormalizedListing
from app.models.enums import Channel

logger = logging.getLogger(__name__)


class Source(Protocol):
    channel: Channel
    name: str

    def fetch(self, query: str) -> list[NormalizedListing]:
        ...


class _ApifySource:
    """Shared base for Apify-backed channels (Kleinanzeigen, willhaben)."""

    def __init__(
        self,
        channel: Channel,
        name: str,
        apify: ApifyClient,
        actor: str,
        max_items: int,
    ) -> None:
        self.channel = channel
        self.name = name
        self.apify = apify
        self.actor = actor
        self.max_items = max_items

    def fetch(self, query: str) -> list[NormalizedListing]:
        items = self.apify.run_actor_get_items(
            self.actor, build_run_input(query), max_items=self.max_items
        )
        out: list[NormalizedListing] = []
        for item in items:
            normalized = normalize_apify_item(item, self.channel)
            if normalized is not None:
                out.append(normalized)
        return out


class KleinanzeigenSource(_ApifySource):
    def __init__(self, apify: ApifyClient, actor: str, max_items: int) -> None:
        super().__init__(Channel.KLEINANZEIGEN, "kleinanzeigen", apify, actor, max_items)


class WillhabenSource(_ApifySource):
    def __init__(self, apify: ApifyClient, actor: str, max_items: int) -> None:
        super().__init__(Channel.WILLHABEN, "willhaben", apify, actor, max_items)


class EbayBrowseSource:
    channel = Channel.EBAY_BROWSE
    name = "ebay_browse"

    def __init__(self, client: EbayBrowseClient, limit: int) -> None:
        self.client = client
        self.limit = limit

    def fetch(self, query: str) -> list[NormalizedListing]:
        items = self.client.search_active(query, limit=self.limit)
        out: list[NormalizedListing] = []
        for item in items:
            normalized = normalize_ebay_item(item)
            if normalized is not None:
                out.append(normalized)
        return out


def build_sources(settings: Settings | None = None) -> list[Source]:
    """Build the enabled sources from settings."""
    settings = settings or get_settings()
    sources: list[Source] = []

    if settings.kleinanzeigen_enabled and settings.apify_kleinanzeigen_actor:
        sources.append(
            KleinanzeigenSource(
                ApifyClient(),
                settings.apify_kleinanzeigen_actor,
                settings.apify_max_items_per_query,
            )
        )
    if settings.willhaben_enabled and settings.apify_willhaben_actor:
        sources.append(
            WillhabenSource(
                ApifyClient(),
                settings.apify_willhaben_actor,
                settings.apify_max_items_per_query,
            )
        )
    if settings.ebay_browse_enabled and settings.ebay_client_id:
        sources.append(
            EbayBrowseSource(EbayBrowseClient(), settings.ebay_browse_limit)
        )

    if not sources:
        logger.warning("no sources enabled/configured; poll will be a no-op")
    return sources
