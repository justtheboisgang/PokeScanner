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
  3. Search TCGdex for the title's name tokens, keep only cards whose printed
     number matches, and resolve only when exactly ONE distinct card remains.
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


# Unambiguous bundle words. Matched anywhere in the text so German compounds
# are caught too ("Pokemon-Kartensammlung"). "sammel" is deliberately NOT here:
# "Sammelkarte" is the ordinary German word for a SINGLE trading card, and
# blocking on it threw away exactly the single-card listings we want.
_BUNDLE_SUBSTRINGS = ("konvolut", "sammlung", "kiloware", "sortiment")

# Short or ambiguous words — whole words only, so they cannot fire inside an
# unrelated word.
_BUNDLE_WORDS = re.compile(
    r"\b(?:lot|bundle|posten|paket|ordner|mappe|album|karton|kiste|menge|"
    r"diverse|verschiedene)\b",
    re.IGNORECASE,
)


def looks_like_bundle(text: str) -> bool:
    low = text.lower()
    return any(h in low for h in _BUNDLE_SUBSTRINGS) or bool(
        _BUNDLE_WORDS.search(text)
    )


def normalize_number(value: object) -> str:
    """Compare card numbers regardless of leading zeros ("002" == "2")."""
    raw = str(value).strip()
    return str(int(raw)) if raw.isdigit() else raw.lower()


def card_local_id(card: dict) -> str | None:
    """The number printed on the card.

    TCGdex brief cards usually carry ``localId``, but not always — and relying
    on it alone silently made every lookup fail. Ids look like "base1-63", so
    the segment after the last dash is the same number.
    """
    raw = card.get("localId")
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    cid = card.get("id")
    if cid and "-" in str(cid):
        return str(cid).rsplit("-", 1)[-1]
    return None

# A set-number like "4/102" pins a title to one specific card slot. The
# denominator is the set's card count and tells sets with the same card number
# apart ("2/102" is Base Set, not one of the other sets that also have a 2).
_NUMBER_RE = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")

# Jubilee/anniversary reprints carry the ORIGINAL's numbering but are worth a
# fraction of it. Resolving "Turtok 2/102 ... Celebration 25. Jubiläum" to the
# 1999 Base Set card would invent a huge profit — exactly what R3 forbids. Such
# titles stay unbewertbar and go to the operator.
_REPRINT_SUBSTRINGS = ("celebration", "jubil", "classic collection", "anniversar")
_REPRINT_WORDS = re.compile(
    r"\b(?:promo|reprint|neudruck|nachdruck|replica|reprodukt)\b", re.IGNORECASE
)


def looks_like_reprint(text: str) -> bool:
    low = text.lower()
    return any(h in low for h in _REPRINT_SUBSTRINGS) or bool(
        _REPRINT_WORDS.search(text)
    )

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
        # Aus echten eBay-Titeln: Wortkoerper, die keine Kartennamen sind und
        # sonst — weil laenger — den echten Namen aus der Suche verdraengen.
        "sammelkarte",
        "sammelkarten",
        "sammelkartenspiel",
        "tcg",
        "wotc",
        "pkm",
        "komplette",
        "komplett",
        "stueck",
        "stück",
        # Set-Namen: TCGdex sucht nach KARTEN-Namen, hier faenden sie nichts.
        "fossil",
        "jungle",
        "rocket",
        "team",
        "gym",
        "neo",
        "expedition",
        "edition",
        # Zustand / Beschreibung.
        "excellent",
        "nearmint",
        "bespielt",
        "gebraucht",
        "fehldruck",
        "misscut",
        "swirl",
        "franzoesisch",
        "französisch",
        "deutsche",
        "sammlung",
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


def _says_german(low: str) -> bool:
    return "deutsch" in low or "german" in low


def _language_from_title(low: str, default: Language) -> Language:
    if "englisch" in low or "english" in low:
        return Language.EN
    if _says_german(low):
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

    def _set_sizes(self, lang_code: str) -> dict[str, int]:
        try:
            return self.tcgdex.set_sizes(lang_code)
        except Exception:
            logger.debug("tcgdex set list unavailable", exc_info=True)
            return {}

    def resolve(
        self,
        title: str,
        description: str | None,
        trace: list[str] | None = None,
    ) -> ResolvedCard | None:
        def note(msg: str) -> None:
            if trace is not None:
                trace.append(msg)

        text = title or ""
        low = text.lower()

        # Gate 1a: bundles never auto-resolve.
        if looks_like_bundle(text):
            note("Tor 1a: als Konvolut erkannt (Bundle-Stichwort) -> unbewertbar")
            return None
        note("Tor 1a: kein Konvolut-Stichwort — weiter")

        # Gate 1a': reprints reuse the original's numbering at a fraction of the
        # value. An automatic value here would be a fantasy, so: hands off.
        if looks_like_reprint(text):
            note("Tor 1a: Neudruck/Jubilaeum erkannt -> unbewertbar (Wert waere erfunden)")
            return None

        # Gate 1b: require a set-number ("4/102") — one specific card slot.
        m = _NUMBER_RE.search(text)
        if not m:
            note("Tor 1b: keine Kartennummer wie 4/102 im Titel -> unbewertbar")
            return None
        local_id = normalize_number(m.group(1))
        set_size = int(m.group(2))
        note(f"Tor 1b: Kartennummer {m.group(1)}/{m.group(2)} gefunden")

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
            note("Tor 2: kein brauchbares Namenswort im Titel -> unbewertbar")
            return None
        note(f"Tor 2: Namenswoerter fuer die Suche: {', '.join(tokens)}")

        lang_code = "de" if self.lang == Language.DE else "en"

        def search(lang: str) -> dict[str, dict]:
            found: dict[str, dict] = {}
            for token in tokens:
                try:
                    results = self.tcgdex.search_cards(token, lang)
                except Exception:
                    logger.debug(
                        "tcgdex search failed for token %r (%s)", token, lang,
                        exc_info=True,
                    )
                    continue
                note(f"  TCGdex[{lang}] '{token}': {len(results)} Treffer")
                for card in results:
                    cid = card.get("id")
                    if not cid:
                        continue
                    if (
                        (local := card_local_id(card)) is not None
                        and normalize_number(local) == local_id
                    ):
                        found[str(cid)] = card
            return found

        matches = search(lang_code)
        resolved_via = lang_code

        # Very many eBay titles carry the card's ENGLISH name even on the German
        # market ("Growlithe 004/020", "Bulbasaur Base Set"). A German-only
        # search finds nothing for those — Growlithe is "Fukano" in German — so
        # every such listing silently stayed unbewertbar. TCGdex ids are the
        # same in every language, so a second pass in English costs nothing but
        # a free lookup and rescues the whole international half of the feed.
        if not matches and lang_code != "en":
            note("  nichts auf Deutsch gefunden — zweiter Versuch auf Englisch")
            matches = search("en")
            if matches:
                resolved_via = "en"

        # The denominator narrows several same-numbered cards down to the set
        # that actually has that many cards.
        if len(matches) > 1:
            sizes = self._set_sizes(lang_code)
            narrowed = {
                cid: card
                for cid, card in matches.items()
                if sizes.get(str(cid).rsplit("-", 1)[0]) == set_size
            }
            if len(narrowed) == 1:
                note(
                    f"Tor 2: {len(matches)} Kandidaten, per Set-Groesse /{set_size} "
                    f"eingegrenzt auf {next(iter(narrowed))}"
                )
                matches = narrowed
            elif narrowed:
                matches = narrowed

        # Gate 2: exactly one distinct card, or it's ambiguous -> unbewertbar.
        if len(matches) != 1:
            note(
                f"Tor 2: {len(matches)} Karten mit Nummer {local_id} — "
                + ("keine gefunden" if not matches
                   else "mehrdeutig: " + ", ".join(matches))
                + " -> unbewertbar"
            )
            return None

        card = next(iter(matches.values()))
        name = card.get("name")
        if not name:
            note("Tor 2: Treffer ohne Namen -> unbewertbar")
            return None
        note(f"Aufgeloest: {name} ({card['id']})")
        # Which language actually found the card is evidence in itself: a title
        # that only matches the English card names is an English card ("Bulbasaur
        # Shadowless Base Set"), not a German one. Getting this wrong would send
        # the cascade down the DE->EN language factor for no reason. An explicit
        # "deutsch" in the title still wins over the inference.
        language = _language_from_title(low, self.lang)
        if resolved_via == "en" and not _says_german(low):
            language = Language.EN
            note("Sprache: über die englischen Namen gefunden -> als EN gewertet")

        return ResolvedCard(
            tcgdex_id=str(card["id"]),
            name=str(name),
            number=f"{int(m.group(1))}/{int(m.group(2))}",
            language=language,
            printing=_printing_from_title(low),
        )
