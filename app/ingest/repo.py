"""Database operations for ingestion (dedup, candidate creation).

Within-channel dedup uses (channel, external_id): a re-seen listing updates
last_seen_at and does NOT re-alert. Cross-channel image-hash dedup (§5) waits for
a second channel and is not implemented here.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest.normalized import NormalizedListing
from app.models.candidate import Candidate
from app.models.listing import Listing


def upsert_listing(
    session: Session, normalized: NormalizedListing
) -> tuple[Listing, bool]:
    """Insert a listing, or update last_seen_at if already known.

    Returns (listing, is_new). is_new=False means it was seen before (no re-alert).
    Dedup is per channel on external_id; cross-channel dedup is image-hash based.
    """
    existing = session.scalar(
        select(Listing).where(
            Listing.channel == normalized.channel,
            Listing.external_id == normalized.external_id,
        )
    )
    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.last_seen_at = now
        # Keep price/title fresh in case the seller edited the ad.
        existing.price = normalized.price
        existing.title = normalized.title
        return existing, False

    listing = Listing(
        channel=normalized.channel,
        external_id=normalized.external_id,
        title=normalized.title,
        description=normalized.description,
        price=normalized.price,
        currency=normalized.currency,
        location=normalized.location,
        seller_type=normalized.seller_type,
        images=list(normalized.images),
        url=normalized.url,
        listed_at=normalized.listed_at,
        listed_at_precision=normalized.listed_at_precision,
        first_seen_at=now,
        last_seen_at=now,
        raw_payload=normalized.raw_payload,
    )
    session.add(listing)
    session.flush()  # assign listing.id
    return listing, True


def create_candidate(
    session: Session,
    listing: Listing,
    *,
    matched_search_term: str | None,
    alert_reason: str,
) -> Candidate:
    """Create an (unbewertbar) candidate for a fresh, qualifying listing."""
    candidate = Candidate(
        listing_id=listing.id,
        reference_value_id=None,
        estimated_profit=None,  # unbewertbar in Phase 2
        alert_reason=alert_reason,
        matched_search_term=matched_search_term,
        triggering_search_terms=[matched_search_term] if matched_search_term else [],
    )
    session.add(candidate)
    session.flush()  # assign candidate.id
    return candidate


def add_triggering_term(session: Session, listing_id: int, term: str) -> None:
    """Record another active term that surfaced an already-seen listing (§1.1)."""
    candidate = session.scalar(
        select(Candidate).where(Candidate.listing_id == listing_id)
    )
    if candidate is None:
        return
    terms = list(candidate.triggering_search_terms or [])
    if term and term not in terms:
        terms.append(term)
        candidate.triggering_search_terms = terms


def mark_alert_sent(
    session: Session, candidate: Candidate, message_id: str | None
) -> None:
    now = datetime.now(timezone.utc)
    candidate.alert_sent_at = now
    candidate.discord_message_id = message_id
    # Time-to-Contact: from the ad's posting time to the alert (§1.3).
    listing = candidate.listing
    if listing is not None and listing.listed_at is not None:
        listed = listing.listed_at
        if listed.tzinfo is None:
            listed = listed.replace(tzinfo=timezone.utc)
        candidate.time_to_alert_seconds = max(0, int((now - listed).total_seconds()))
