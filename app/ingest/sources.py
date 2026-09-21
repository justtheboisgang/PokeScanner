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
from app.ingest.ebay_browse import item_country, normalize_ebay_item
from app.ingest.kleinanzeigen import (
    build_run_input,
    normalize_apify_item,
    normalize_lexis_item,
)
from app.ingest.normalized import NormalizedListing
from app.models.enums import Channel

logger = logging.getLogger(__name__)

# Default actor input for lexis-solutions/ebay-kleinanzeigen: one search-results
# URL per term. {{search_url}} is filled by build_run_input.
_LEXIS_DEFAULT_INPUT = '{"startUrls":[{"url":"{{search_url}}"}]}'


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
        normalize_fn,
        input_template: str = "",
    ) -> None:
        self.channel = channel
        self.name = name
        self.apify = apify
        self.actor = actor
        self.max_items = max_items
        self.normalize_fn = normalize_fn
        self.input_template = input_template

    def fetch(self, query: str) -> list[NormalizedListing]:
        items = self.apify.run_actor_get_items(
            self.actor,
            build_run_input(query, self.input_template),
            max_items=self.max_items,
        )
        out: list[NormalizedListing] = []
        for item in items:
            normalized = self.normalize_fn(item)
            if normalized is not None:
                out.append(normalized)
        return out


class KleinanzeigenSource(_ApifySource):
    def __init__(
        self, apify: ApifyClient, actor: str, max_items: int, input_template: str = ""
    ) -> None:
        super().__init__(
            Channel.KLEINANZEIGEN,
            "kleinanzeigen",
            apify,
            actor,
            max_items,
            normalize_lexis_item,
            input_template or _LEXIS_DEFAULT_INPUT,
        )


class WillhabenSource(_ApifySource):
    def __init__(self, apify: ApifyClient, actor: str, max_items: int) -> None:
        super().__init__(
            Channel.WILLHABEN,
            "willhaben",
            apify,
            actor,
            max_items,
            lambda item: normalize_apify_item(item, Channel.WILLHABEN),
        )


class EbayBrowseSource:
    channel = Channel.EBAY_BROWSE
    name = "ebay_browse"

    def __init__(
        self, client: EbayBrowseClient, limit: int, countries: list[str] | None = None
    ) -> None:
        self.client = client
        self.limit = limit
        # Dieselbe Liste, die der Client als Filter mitschickt — hier aber zum
        # NACHPRUEFEN. Leer heisst "weltweit, ich passe selbst auf".
        self.countries = {c.strip().upper() for c in (countries or []) if c.strip()}

    def fetch(self, query: str) -> list[NormalizedListing]:
        # Sortierung steckt im Client (newlyListed): ohne sie liefert eBay nach
        # Relevanz, und neue Angebote blieben unsichtbar.
        items = self.client.search_active(query, limit=self.limit)
        out: list[NormalizedListing] = []
        for item in items:
            # Die Herkunft wird zweimal geprueft: eBay bekommt den Filter
            # mitgeschickt, UND hier wird nachgesehen. Im Live-Betrieb kamen
            # trotz EU-Filter Angebote aus GB und Japan durch — auf die Zusage
            # der API allein ist kein Verlass, und Zoll plus Einfuhrsteuer
            # stecken in keiner Gewinnrechnung.
            if self.countries:
                country = item_country(item)
                if country is not None and country not in self.countries:
                    continue
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
                settings.apify_kleinanzeigen_input,
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
            EbayBrowseSource(
                EbayBrowseClient(),
                settings.ebay_browse_limit,
                settings.ebay_location_country_list,
            )
        )

    if not sources:
        logger.warning("no sources enabled/configured; poll will be a no-op")
    return sources
