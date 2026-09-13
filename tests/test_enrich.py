"""Enrichment: text extraction, vision analyzer, service (§10/§11)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import httpx

from app.alerts.discord import DiscordNotifier
from app.enrich.service import EnrichmentService
from app.enrich.text_extract import extract_condition_flags
from app.enrich.vision import VisionAnalyzer
from app.models.candidate import Candidate
from app.models.enrichment import Enrichment
from app.models.enums import Channel, SellerType
from app.models.listing import Listing


# --- text extraction (pure) -----------------------------------------------

def test_extract_condition_flags_finds_defects():
    flags = extract_condition_flags(
        "Alte Pokemon Karten", "Ein paar Karten haben einen Knick und Kratzer, bespielt."
    )
    assert "knick" in flags
    assert "kratzer" in flags
    assert "bespielt" in flags


def test_extract_condition_flags_none_when_clean():
    assert extract_condition_flags("Pokemon Sammlung", "Top Zustand, wie neu") == []


def test_extract_condition_flags_handles_empty():
    assert extract_condition_flags(None, None) == []


# --- vision analyzer (fake client) ----------------------------------------

class _FakeMessages:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def _text_response(text, stop_reason="end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
    )


def _img_transport(status=200):
    """MockTransport returning fake JPEG bytes for any image download."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, content=b"FAKEJPEGDATA", headers={"content-type": "image/jpeg"}
        )

    return httpx.MockTransport(handler)


def test_vision_analyze_returns_summary():
    client = _FakeClient(_text_response("Sieht nach e-Serie aus, deutsche Karten."))
    analyzer = VisionAnalyzer(
        model="claude-opus-5", enabled=True, client=client, http_transport=_img_transport()
    )
    result = analyzer.analyze(
        ["https://img/1.jpg", "https://img/2.jpg"], title="Alte Pokemon Karten"
    )
    assert result is not None
    assert "e-Serie" in result.summary
    assert result.model == "claude-opus-5"
    # Two downloaded base64 image blocks + one text block sent.
    sent = client.messages.calls[0]["messages"][0]["content"]
    images = [b for b in sent if b["type"] == "image"]
    assert len(images) == 2
    assert images[0]["source"]["type"] == "base64"


def test_vision_respects_max_images():
    client = _FakeClient(_text_response("ok"))
    analyzer = VisionAnalyzer(
        enabled=True, client=client, max_images=1, http_transport=_img_transport()
    )
    analyzer.analyze(["https://img/a.jpg", "https://img/b.jpg"], title="x")
    images = [b for b in client.messages.calls[0]["messages"][0]["content"] if b["type"] == "image"]
    assert len(images) == 1


def test_vision_refusal_returns_none():
    client = _FakeClient(_text_response("", stop_reason="refusal"))
    analyzer = VisionAnalyzer(enabled=True, client=client, http_transport=_img_transport())
    assert analyzer.analyze(["https://img/a.jpg"], title="x") is None


def test_vision_returns_none_when_images_undownloadable():
    client = _FakeClient(_text_response("should not be used"))
    analyzer = VisionAnalyzer(
        enabled=True, client=client, http_transport=_img_transport(status=404)
    )
    assert analyzer.analyze(["https://img/a.jpg"], title="x") is None


def test_vision_disabled_returns_none():
    client = _FakeClient(_text_response("should not be used"))
    analyzer = VisionAnalyzer(enabled=False, client=client, http_transport=_img_transport())
    assert analyzer.analyze(["https://img/a.jpg"], title="x") is None


def test_vision_no_images_returns_none():
    client = _FakeClient(_text_response("x"))
    analyzer = VisionAnalyzer(enabled=True, client=client, http_transport=_img_transport())
    assert analyzer.analyze([], title="x") is None


# --- enrichment service (sqlite + fakes) ----------------------------------

class _FakeNotifier(DiscordNotifier):
    def __init__(self):
        self.edits = []

    @property
    def enabled(self):
        return True

    def edit(self, message_id, content):
        self.edits.append((message_id, content))


def _seed_candidate(db, *, images, description, message_id="msg-1"):
    listing = Listing(
        channel=Channel.KLEINANZEIGEN,
        external_id="e1",
        title="Alte Pokemon Karten",
        description=description,
        price=Decimal("60"),
        currency="EUR",
        location="Berlin",
        seller_type=SellerType.PRIVATE,
        images=images,
        url="https://x",
    )
    db.add(listing)
    db.flush()
    cand = Candidate(
        listing_id=listing.id,
        matched_search_term="alte pokemon karten",
        alert_sent_at=datetime.now(timezone.utc),
        discord_message_id=message_id,
    )
    db.add(cand)
    db.commit()
    return cand.id


def test_enrich_stores_flags_and_runs_vision_and_edits_embed(scoped_factory, db):
    cand_id = _seed_candidate(
        db, images=["https://img/1.jpg"], description="mit Knick und Kratzer"
    )
    notifier = _FakeNotifier()
    vision = VisionAnalyzer(
        enabled=True,
        client=_FakeClient(_text_response("e-Serie, DE")),
        http_transport=_img_transport(),
    )
    service = EnrichmentService(vision, notifier, session_factory=scoped_factory)

    outcome = service.enrich(cand_id, allow_vision=True)
    assert outcome.vision_used is True
    assert "knick" in outcome.condition_flags

    stored = db.query(Enrichment).filter_by(candidate_id=cand_id).one()
    assert stored.vision_used is True
    assert stored.vision_summary == "e-Serie, DE"
    assert "kratzer" in stored.condition_flags
    # Embed edited with enrichment content.
    assert len(notifier.edits) == 1
    assert notifier.edits[0][0] == "msg-1"
    assert notifier.edits[0][1].vision_summary == "e-Serie, DE"


def test_enrich_skips_vision_when_not_allowed(scoped_factory, db):
    cand_id = _seed_candidate(db, images=["https://img/1.jpg"], description="sauber")
    notifier = _FakeNotifier()
    vision = VisionAnalyzer(enabled=True, client=_FakeClient(_text_response("x")))
    service = EnrichmentService(vision, notifier, session_factory=scoped_factory)

    outcome = service.enrich(cand_id, allow_vision=False)
    assert outcome.vision_used is False
    stored = db.query(Enrichment).filter_by(candidate_id=cand_id).one()
    assert stored.vision_used is False
    assert stored.vision_summary is None


def test_enrich_upsert_is_idempotent(scoped_factory, db):
    cand_id = _seed_candidate(db, images=[], description="mit Riss")
    notifier = _FakeNotifier()
    vision = VisionAnalyzer(enabled=False, client=None)
    service = EnrichmentService(vision, notifier, session_factory=scoped_factory)

    service.enrich(cand_id, allow_vision=True)
    service.enrich(cand_id, allow_vision=True)
    assert db.query(Enrichment).filter_by(candidate_id=cand_id).count() == 1
