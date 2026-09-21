"""Ingestion pipeline integration (Phase 5): sources, dedup, alarm, alert."""

from __future__ import annotations

from decimal import Decimal

from app.alerts.discord import DiscordNotifier
from app.config import Settings
from app.config_data import SearchTerms
from app.enrich.service import EnrichmentService
from app.enrich.vision import VisionAnalyzer
from app.ingest.normalized import NormalizedListing
from app.ingest.pipeline import IngestionPipeline
from app.models.candidate import Candidate
from app.models.enums import Channel, SellerType
from app.models.listing import Listing

TERMS = SearchTerms(
    positive=("alte pokemon karten",),
    negative=("repro", "psa"),
    active=("alte pokemon karten",),
)


class FakeSource:
    def __init__(self, channel, name, mapping):
        self.channel = channel
        self.name = name
        self.mapping = mapping

    def fetch(self, term):
        return list(self.mapping.get(term, []))


class FakeNotifier(DiscordNotifier):
    def __init__(self):
        self.sent = []

    @property
    def enabled(self):
        return True

    def send(self, content):
        self.sent.append(content)
        return f"msg-{len(self.sent)}"

    def edit(self, message_id, content):
        pass


class FakeHasher:
    def __init__(self, constant=None):
        self.constant = constant

    def hash_url(self, url):
        return self.constant if self.constant is not None else f"h-{url}"


def _listing(channel, ext, title="Alte Pokemon Karten", price="60", images=("u1",), desc=""):
    return NormalizedListing(
        channel=channel,
        external_id=ext,
        title=title,
        description=desc,
        price=Decimal(price) if price is not None else None,
        currency="EUR",
        location="Berlin",
        seller_type=SellerType.PRIVATE,
        images=list(images),
        url=f"https://x/{ext}",
    )


def _pipeline(sources, notifier, scoped_factory, *, hasher=None, settings=None):
    settings = settings or Settings()
    return IngestionPipeline(
        sources,
        notifier,
        session_factory=scoped_factory,
        settings=settings,
        search_terms=TERMS,
        enrichment=EnrichmentService(
            VisionAnalyzer(enabled=False), notifier, session_factory=scoped_factory
        ),
        hasher=hasher,
    )


def test_pipeline_alerts_new_listing(scoped_factory, db):
    src = FakeSource(
        Channel.KLEINANZEIGEN, "kleinanzeigen",
        {"alte pokemon karten": [_listing(Channel.KLEINANZEIGEN, "k1")]},
    )
    notifier = FakeNotifier()
    stats = _pipeline([src], notifier, scoped_factory, hasher=FakeHasher()).poll()

    assert stats.new_listings == 1
    assert stats.alerts_sent == 1
    assert len(notifier.sent) == 1
    assert db.query(Candidate).count() == 1
    cand = db.query(Candidate).one()
    assert cand.matched_search_term == "alte pokemon karten"
    assert db.query(Listing).one().image_hash == "h-u1"


def test_pipeline_excludes_negative_term(scoped_factory, db):
    src = FakeSource(
        Channel.KLEINANZEIGEN, "kleinanzeigen",
        {"alte pokemon karten": [_listing(Channel.KLEINANZEIGEN, "k1", title="Repro Glurak")]},
    )
    notifier = FakeNotifier()
    stats = _pipeline([src], notifier, scoped_factory, hasher=FakeHasher()).poll()

    assert stats.skipped_excluded == 1
    assert stats.alerts_sent == 0
    assert db.query(Candidate).count() == 0
    assert db.query(Listing).count() == 1  # stored as calibration data


def test_pipeline_seen_dedup_no_realert(scoped_factory, db):
    src = FakeSource(
        Channel.KLEINANZEIGEN, "kleinanzeigen",
        {"alte pokemon karten": [_listing(Channel.KLEINANZEIGEN, "k1")]},
    )
    notifier = FakeNotifier()
    pipe = _pipeline([src], notifier, scoped_factory, hasher=FakeHasher())
    pipe.poll()
    stats2 = pipe.poll()

    assert stats2.skipped_seen == 1
    assert stats2.alerts_sent == 0
    assert db.query(Candidate).count() == 1  # only the first poll alerted


def test_pipeline_cross_channel_dedup(scoped_factory, db):
    wh = FakeSource(
        Channel.WILLHABEN, "willhaben",
        {"alte pokemon karten": [_listing(Channel.WILLHABEN, "w1", price="60")]},
    )
    ka = FakeSource(
        Channel.KLEINANZEIGEN, "kleinanzeigen",
        {"alte pokemon karten": [_listing(Channel.KLEINANZEIGEN, "k1", price="62")]},
    )
    notifier = FakeNotifier()
    # Same image hash for both -> cross-posted duplicate.
    stats = _pipeline(
        [wh, ka], notifier, scoped_factory, hasher=FakeHasher(constant="SAMEHASH")
    ).poll()

    assert stats.alerts_sent == 1
    assert stats.deduped == 1
    assert db.query(Candidate).count() == 1
    assert db.query(Listing).count() == 2  # both listings stored


# --- Block 5: kanalabhängige Preis-Pflicht ---------------------------------


def _poll_one(scoped_factory, channel, name, price):
    src = FakeSource(
        channel,
        name,
        {"alte pokemon karten": [_listing(channel, f"{name}-{price}", price=price)]},
    )
    return _pipeline([src], FakeNotifier(), scoped_factory, hasher=FakeHasher()).poll()


def test_kleinanzeigen_without_price_still_fires(scoped_factory, db):
    """VB/leer ist bei Konvoluten der Normalfall und genau der Werthebel (R4)."""
    stats = _poll_one(scoped_factory, Channel.KLEINANZEIGEN, "kleinanzeigen", None)
    assert stats.alerts_sent == 1
    assert stats.skipped_excluded == 0


def test_ebay_without_price_does_not_fire(scoped_factory, db):
    """Auf eBay ist ein Treffer ohne Preis kein Deal-Signal, sondern Rauschen."""
    stats = _poll_one(scoped_factory, Channel.EBAY_BROWSE, "ebay_browse", None)
    assert stats.alerts_sent == 0
    assert stats.skipped_excluded == 1


def test_ebay_with_price_fires(scoped_factory, db):
    stats = _poll_one(scoped_factory, Channel.EBAY_BROWSE, "ebay_browse", "40")
    assert stats.alerts_sent == 1


# --- Zustell-Grenze pro Scan (keine Alarmschwelle!) -------------------------


def _many_listings(channel, n):
    # Eigenes Bild je Anzeige, sonst greift der Cross-Channel-Dedup (gleicher Hash).
    return [
        _listing(channel, f"m{i}", title="Alte Pokemon Karten", images=(f"u{i}",))
        for i in range(n)
    ]


def _pipeline_capped(scoped_factory, notifier, cap):
    settings = Settings(ALERT_MAX_PER_POLL=cap)
    src = FakeSource(
        Channel.KLEINANZEIGEN,
        "kleinanzeigen",
        {"alte pokemon karten": _many_listings(Channel.KLEINANZEIGEN, 10)},
    )
    return _pipeline([src], notifier, scoped_factory, hasher=FakeHasher(),
                     settings=settings)


def test_alert_cap_limits_discord_messages(scoped_factory, db):
    notifier = FakeNotifier()
    stats = _pipeline_capped(scoped_factory, notifier, cap=3).poll()
    assert stats.alerts_sent == 3
    assert stats.alerts_suppressed == 7
    # 3 Embeds + genau EINE Sammelmeldung, statt zehn Nachrichten.
    assert len(notifier.sent) == 3


def test_capped_finds_are_still_stored_and_countable(scoped_factory, db):
    """Die Grenze ist eine Zustellgrenze — gefunden wird alles, nichts geht verloren."""
    from app.models.listing import Listing

    notifier = FakeNotifier()
    stats = _pipeline_capped(scoped_factory, notifier, cap=3).poll()
    assert stats.new_listings == 10
    # Alle zehn liegen in der Datenbank und erscheinen damit im Live Feed.
    assert db.query(Listing).count() == 10
    # Und die Messung je Suchbegriff zaehlt weiterhin alle zehn (Diagnose).
    assert stats.per_term_new["alte pokemon karten"] == 10


def test_no_cap_notice_when_under_the_limit(scoped_factory, db):
    notifier = FakeNotifier()
    stats = _pipeline_capped(scoped_factory, notifier, cap=50).poll()
    assert stats.alerts_sent == 10
    assert stats.alerts_suppressed == 0


# --- Konto-Limit: einmal melden, nicht zehnmal ------------------------------


class _FailingSource:
    channel = Channel.KLEINANZEIGEN
    name = "kleinanzeigen"

    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def fetch(self, term):
        self.calls += 1
        raise self.exc


def test_account_level_failure_stops_the_source_after_one_try(scoped_factory, db):
    """Ein Konto-Limit gilt fuer jeden Begriff — neunmal nachfassen ist sinnlos."""
    from app.clients.exceptions import ClientError

    src = _FailingSource(
        ClientError('Apify error 403: {"type":"platform-feature-disabled",'
                    '"message":"Monthly usage hard limit exceeded"}')
    )
    terms = SearchTerms(positive=(), negative=(), active=("a", "b", "c", "d"))
    pipe = IngestionPipeline(
        [src], FakeNotifier(), session_factory=scoped_factory,
        settings=Settings(), search_terms=terms, hasher=FakeHasher(),
        enrichment=EnrichmentService(
            VisionAnalyzer(enabled=False), FakeNotifier(),
            session_factory=scoped_factory,
        ),
    )
    stats = pipe.poll()
    assert src.calls == 1          # nicht vier Mal
    assert stats.errors == 1


def test_transient_failure_keeps_trying_the_other_terms(scoped_factory, db):
    """Ein einzelner Aussetzer darf die ganze Quelle nicht abwuergen."""
    from app.clients.exceptions import ClientError

    src = _FailingSource(ClientError("Apify error 502: upstream hiccup"))
    terms = SearchTerms(positive=(), negative=(), active=("a", "b", "c"))
    pipe = IngestionPipeline(
        [src], FakeNotifier(), session_factory=scoped_factory,
        settings=Settings(), search_terms=terms, hasher=FakeHasher(),
        enrichment=EnrichmentService(
            VisionAnalyzer(enabled=False), FakeNotifier(),
            session_factory=scoped_factory,
        ),
    )
    stats = pipe.poll()
    assert src.calls == 3
    assert stats.errors == 3


# --- Die Automatik muss im ECHTEN Worker haengen, nicht nur im Test --------


def test_production_pipeline_has_auto_valuation_wired():
    """Der Worker baut seine Pipeline ueber build_pipeline().

    Wuerde dort eine EnrichmentService-Instanz mitgegeben, liefe die
    automatische Bewertung im Dauerbetrieb gar nicht — jeder neue Treffer bliebe
    unbewertbar, ohne dass irgendwo ein Fehler auftaucht. Genau so etwas faellt
    sonst erst Wochen spaeter auf.
    """
    from app.ingest.pipeline import build_pipeline

    settings = Settings(ENRICH_AUTO_VALUE_ENABLED=True)
    pipeline = build_pipeline(notifier=FakeNotifier(), settings=settings)
    assert pipeline.enrichment.auto_valuer is not None


def test_auto_valuation_can_be_switched_off():
    from app.ingest.pipeline import build_pipeline

    settings = Settings(ENRICH_AUTO_VALUE_ENABLED=False)
    pipeline = build_pipeline(notifier=FakeNotifier(), settings=settings)
    assert pipeline.enrichment.auto_valuer is None


# --- Bewertung haengt nicht an Discord --------------------------------------


def _pipeline_with_valuer(scoped_factory, notifier, cap, seen):
    """Pipeline mit Zustellgrenze UND einem Bewerter, der mitschreibt."""
    def _valuer(session, candidate):
        seen.append(candidate.id)
        return None

    settings = Settings(ALERT_MAX_PER_POLL=cap)
    src = FakeSource(
        Channel.KLEINANZEIGEN,
        "kleinanzeigen",
        {"alte pokemon karten": _many_listings(Channel.KLEINANZEIGEN, 10)},
    )
    return IngestionPipeline(
        [src],
        notifier,
        session_factory=scoped_factory,
        settings=settings,
        search_terms=TERMS,
        enrichment=EnrichmentService(
            VisionAnalyzer(enabled=False),
            notifier,
            session_factory=scoped_factory,
            auto_valuer=_valuer,
        ),
        hasher=FakeHasher(),
    )


def test_capped_candidates_are_still_valued(scoped_factory, db):
    """Die Zustellgrenze darf die Bewertung nicht mitnehmen.

    Vorher hing die Anreicherung hinter dem Discord-Versand: bei Kappe 50 und
    220 Funden blieben 170 Kandidaten unangetastet und fuer immer "noch nicht
    bewertet". Die Grenze gilt fuer Discord, nicht fuer die Bewertung.
    """
    seen: list[int] = []
    notifier = FakeNotifier()
    stats = _pipeline_with_valuer(scoped_factory, notifier, 3, seen).poll()

    assert stats.alerts_sent == 3
    assert stats.alerts_suppressed == 7
    assert len(notifier.sent) == 3      # Discord bleibt gedeckelt
    assert len(seen) == 10              # bewertet wird trotzdem alles


def test_failed_discord_send_does_not_skip_valuation(scoped_factory, db):
    """Ein Discord-Ausfall darf die Karte nicht unbewertet zuruecklassen."""
    class _BrokenNotifier(FakeNotifier):
        def send(self, content):
            raise RuntimeError("Discord weg")

    seen: list[int] = []
    notifier = _BrokenNotifier()
    stats = _pipeline_with_valuer(scoped_factory, notifier, 50, seen).poll()

    assert stats.alerts_sent == 0
    assert stats.errors == 10
    assert len(seen) == 10
    # Kein Alarm gilt als gesendet — time-to-alert bleibt ehrlich.
    assert db.query(Candidate).filter(Candidate.alert_sent_at.isnot(None)).count() == 0
