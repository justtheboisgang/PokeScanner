"""Cross-channel dedup: aHash, image fetch, duplicate lookup (§5)."""

from __future__ import annotations

import io
from decimal import Decimal

import httpx
from PIL import Image

from app.ingest.dedup import (
    ImageHasher,
    compute_ahash,
    find_duplicate_listing,
    hamming,
)
from app.models.candidate import Candidate
from app.models.enums import Channel, SellerType
from app.models.listing import Listing


def _png_bytes(color=(120, 30, 200), size=(16, 16)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _gradient_png() -> bytes:
    img = Image.new("L", (16, 16))
    img.putdata([(i * 255) // 255 for i in range(16 * 16)])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_ahash_stable_and_distinct():
    a = compute_ahash(_png_bytes())
    assert a == compute_ahash(_png_bytes())  # deterministic
    assert len(a) == 16
    b = compute_ahash(_gradient_png())
    assert a != b
    assert hamming(a, b) > 0
    assert hamming(a, a) == 0


def test_image_hasher_fetches_and_hashes():
    png = _png_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    hasher = ImageHasher(transport=httpx.MockTransport(handler))
    assert hasher.hash_url("https://img/1.png") == compute_ahash(png)


def test_image_hasher_returns_none_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    hasher = ImageHasher(transport=httpx.MockTransport(handler))
    assert hasher.hash_url("https://img/missing.png") is None


def test_image_hasher_rejects_non_http_scheme():
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, content=_png_bytes())

    hasher = ImageHasher(transport=httpx.MockTransport(handler))
    # file:// and other schemes must not be fetched (SSRF hygiene).
    assert hasher.hash_url("file:///etc/passwd") is None
    assert hasher.hash_url("ftp://internal/x") is None
    assert called["n"] == 0


def _listing_with_candidate(db, channel, ext, image_hash, price):
    listing = Listing(
        channel=channel,
        external_id=ext,
        title="Alte Pokemon Karten",
        price=Decimal(str(price)),
        currency="EUR",
        location="Berlin",
        seller_type=SellerType.PRIVATE,
        images=[],
        image_hash=image_hash,
    )
    db.add(listing)
    db.flush()
    db.add(Candidate(listing_id=listing.id))
    db.commit()
    return listing


def test_find_duplicate_matches_across_channels_within_price_tolerance(db):
    a = _listing_with_candidate(db, Channel.WILLHABEN, "w1", "aaaabbbbccccdddd", 60)
    # New kleinanzeigen listing, same image hash, price within tolerance.
    b = Listing(
        channel=Channel.KLEINANZEIGEN,
        external_id="k1",
        title="x",
        price=Decimal("62"),
        currency="EUR",
        seller_type=SellerType.PRIVATE,
        images=[],
        image_hash="aaaabbbbccccdddd",
    )
    db.add(b)
    db.flush()

    dup = find_duplicate_listing(
        db,
        image_hash="aaaabbbbccccdddd",
        price=Decimal("62"),
        exclude_listing_id=b.id,
        price_tolerance=Decimal("5"),
    )
    assert dup is not None
    assert dup.id == a.id


def test_find_duplicate_respects_price_tolerance(db):
    _listing_with_candidate(db, Channel.WILLHABEN, "w2", "1111222233334444", 60)
    dup = find_duplicate_listing(
        db,
        image_hash="1111222233334444",
        price=Decimal("200"),  # far outside tolerance
        exclude_listing_id=999,
        price_tolerance=Decimal("5"),
    )
    assert dup is None


def test_find_duplicate_none_when_hash_differs(db):
    _listing_with_candidate(db, Channel.WILLHABEN, "w3", "1111222233334444", 60)
    dup = find_duplicate_listing(
        db,
        image_hash="ffffffffffffffff",
        price=Decimal("60"),
        exclude_listing_id=999,
        price_tolerance=Decimal("5"),
    )
    assert dup is None


def test_find_duplicate_hamming_tolerance_matches_near_hash(db):
    # Stored hash and query hash differ by 1 bit (…e vs …f).
    a = _listing_with_candidate(db, Channel.WILLHABEN, "w4", "aaaabbbbccccddde", 60)

    # Exact match (threshold 0) does not catch the 1-bit difference.
    assert (
        find_duplicate_listing(
            db,
            image_hash="aaaabbbbccccdddf",
            price=Decimal("61"),
            exclude_listing_id=999,
            price_tolerance=Decimal("5"),
        )
        is None
    )
    # With Hamming tolerance >=1 it matches.
    dup = find_duplicate_listing(
        db,
        image_hash="aaaabbbbccccdddf",
        price=Decimal("61"),
        exclude_listing_id=999,
        price_tolerance=Decimal("5"),
        hamming_threshold=2,
    )
    assert dup is not None
    assert dup.id == a.id


def test_find_duplicate_hamming_still_respects_price(db):
    _listing_with_candidate(db, Channel.WILLHABEN, "w5", "aaaabbbbccccddde", 60)
    dup = find_duplicate_listing(
        db,
        image_hash="aaaabbbbccccdddf",
        price=Decimal("500"),  # outside tolerance
        exclude_listing_id=999,
        price_tolerance=Decimal("5"),
        hamming_threshold=2,
    )
    assert dup is None
