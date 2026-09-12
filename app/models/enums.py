"""Domain enums.

Kept deliberately small and explicit. `era` is intentionally NOT an enum: the
alert universe is "alle Ären" (§7) and eras are open-ended (WOTC, e-Series,
EX-Ära, Lv.X, LEGEND, ...), so it is stored as a free string on `card`.
"""

from __future__ import annotations

import enum


class Language(str, enum.Enum):
    """Actual card language. Distinct from the eBay *market* (ebay.de)."""

    DE = "de"
    EN = "en"


class Condition(str, enum.Enum):
    """Card condition. Default when unspecified is PLAYED (§6, konservativ)."""

    MINT = "mint"
    NEAR_MINT = "near_mint"
    EXCELLENT = "excellent"
    GOOD = "good"
    LIGHT_PLAYED = "light_played"
    PLAYED = "played"
    POOR = "poor"
    UNKNOWN = "unknown"


#: Zustands-Default bei fehlender Angabe (§6).
DEFAULT_CONDITION = Condition.PLAYED


class Printing(str, enum.Enum):
    """Printing / edition variant. Prices hang on the variant, never the card."""

    NORMAL = "normal"
    HOLO = "holo"
    REVERSE_HOLO = "reverse_holo"
    FIRST_EDITION = "first_edition"
    UNLIMITED = "unlimited"
    UNKNOWN = "unknown"


class Channel(str, enum.Enum):
    """Sourcing / market channel."""

    KLEINANZEIGEN = "kleinanzeigen"
    EBAY = "ebay"
    EBAY_BROWSE = "ebay_browse"
    WILLHABEN = "willhaben"
    VINTED = "vinted"
    SOLDCOMPS = "soldcomps"
    MANUAL = "manual"


class SellerType(str, enum.Enum):
    PRIVATE = "private"
    COMMERCIAL = "commercial"
    UNKNOWN = "unknown"


class ReferenceSource(str, enum.Enum):
    """Where a reference value came from (§6 cascade)."""

    SOLDCOMPS = "soldcomps"
    TCGDEX_CARDMARKET = "tcgdex_cardmarket"


class Verdict(str, enum.Enum):
    BUY = "buy"
    SKIP = "skip"
    UNCLEAR = "unclear"


class CounterfeitCheck(str, enum.Enum):
    """Explicit, mandatory step in the decision form (§7). Im Zweifel: nicht kaufen."""

    PASSED = "passed"
    FAILED = "failed"
    UNSURE = "unsure"
    NOT_CHECKED = "not_checked"
