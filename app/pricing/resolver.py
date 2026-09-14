"""Automatic title resolution (Block 2.2) — conservative single-card gate.

The machine only auto-values a listing when its title unambiguously names exactly
ONE card. That is the whole point of R3 honesty: a Konvolut ("Sammlung", "Lot",
"Konvolut") or a vague title carries several cards or none in particular, so we
must NOT invent a reference value for it — it stays unbewertbar and waits for the
operator's manual identification (Block 2.3).

The gate is deliberately precision-over-recall:
  1. Reject any title that looks like a bundle (keyword hints).
  2. Require a set-number pattern (e.g. ``4/102``) — the strongest signal that a
     title is about ONE specific card, not a pile.
  3. Search TCGdex for the title's name tokens, keep only cards whose ``localId``
     matches the number, and resolve only when exactly ONE distinct card remains.
Anything short of that returns None (unbewertbar), which is the normal case.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.clients.tcgdex import TCGdexClient
from app.models.enums import Language, Printing

logger = logging.getLogger(__name__)


@dataclass
class ResolvedCard:
    tcgdex_id: str
    name: str
    number: str | None
    language: Language
    printing: Printing


@runtime_checkable
class TitleResolver(Protocol):
    def resolve(self, title: str, description: str | None) -> ResolvedCard | None: ...


class NullResolver:
    """Default: never auto-resolve. Every candidate stays unbewertbar (R3-safe)."""

    def resolve(self, title: str, description: str | None) -> ResolvedCard | None:
        return None


# Words that mark a listing as a pile of cards, never a single card.
_BUNDLE_HINTS = (
    "konvolut",
    "sammlung",
    "sammel",
    "lot",
    "bundle",
    "posten",
    "paket",
    "kiloware",
    "ordner",
    "mappe",
    "album",
    "karton",
    "kiste",
    "diverse",
    "verschiedene",
    "sortiment",
    "menge",
)

# A set-number like "4/102" pins a title to one specific card slot.
_NUMBER_RE = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")

# Noise tokens that are never a card name (conditions, printings, generic words).
_STOP_TOKENS = frozenset(
    {
        "pokemon",
        "pokémon",
        "karte",
        "karten",
        "card",
        "cards",
        "holo",
        "holos",
        "reverse",
        "rare",
        "edition",
        "auflage",
        "erstauflage",
        "first",
        "mint",
        "played",
        "gespielt",
        "near",
        "german",
        "deutsch",
        "englisch",
        "english",
        "vintage",
        "original",
        "selten",
        "base",
        "set",
        "basis",
    }
)

_TOKEN_RE = re.compile(r"[A-Za-zÄÖÜäöüß]{3,}")


def _printing_from_title(low: str) -> Printing:
    if "reverse" in low:
        return Printing.REVERSE_HOLO
    if "1st" in low or "first" in low or "erstauflage" in low or "1. auflage" in low:
        return Printing.FIRST_EDITION
    if "holo" in low or "glitzer" in low:
        return Printing.HOLO
    return Printing.NORMAL


def _language_from_title(low: str, default: Language) -> Language:
    if "englisch" in low or "english" in low:
        return Language.EN
    if "deutsch" in low or "german" in low:
        return Language.DE
    return default


class SingleCardTitleResolver:
    """Resolve a title to one card, or None. Precision over recall (R3)."""

    def __init__(
        self, tcgdex: TCGdexClient, *, lang: Language = Language.DE, max_searches: int = 3
    ) -> None:
        self.tcgdex = tcgdex
        self.lang = lang
        self.max_searches = max_searches

    def resolve(self, title: str, description: str | None) -> ResolvedCard | None:
        text = title or ""
        low = text.lower()

        # Gate 1a: bundles never auto-resolve.
        if any(hint in low for hint in _BUNDLE_HINTS):
            return None

        # Gate 1b: require a set-number ("4/102") — one specific card slot.
        m = _NUMBER_RE.search(text)
        if not m:
            return None
        local_id = str(int(m.group(1)))

        # Name tokens: longest first, drop noise. Try the strongest few.
        tokens = sorted(
            {
                t
                for t in _TOKEN_RE.findall(text)
                if t.lower() not in _STOP_TOKENS
            },
            key=len,
            reverse=True,
        )[: self.max_searches]
        if not tokens:
            return None

        lang_code = "de" if self.lang == Language.DE else "en"
        matches: dict[str, dict] = {}
        for token in tokens:
            try:
                results = self.tcgdex.search_cards(token, lang_code)
            except Exception:
                logger.debug("tcgdex search failed for token %r", token, exc_info=True)
                continue
            for card in results:
                cid = card.get("id")
                if not cid:
                    continue
                if str(card.get("localId")) == local_id:
                    matches[str(cid)] = card

        # Gate 2: exactly one distinct card, or it's ambiguous -> unbewertbar.
        if len(matches) != 1:
            return None

        card = next(iter(matches.values()))
        name = card.get("name")
        if not name:
            return None
        return ResolvedCard(
            tcgdex_id=str(card["id"]),
            name=str(name),
            number=f"{int(m.group(1))}/{int(m.group(2))}",
            language=_language_from_title(low, self.lang),
            printing=_printing_from_title(low),
        )
