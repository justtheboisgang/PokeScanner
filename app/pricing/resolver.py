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

# Eine Kartennummer bindet den Titel an genau einen Platz im Set. Frueher wurde
# nur "4/102" erkannt — damit fielen Promos, Meisterball-Karten und Trainer-
# Galerien durch, also ausgerechnet die interessanten Einzelkarten:
#   Kronjuwild WHT 007 · Glurak G Lv.X DP45 · Damythir TG06/TG30 · SV085/SV122
#
# Zwei Formen werden akzeptiert:
#   1. Ein Paar "X/Y", beide Seiten optional mit Buchstabenkuerzel.
#   2. Ein Kuerzel plus Zahl ohne Nenner (DP45, WHT 007, SWSH123).
# Eine nackte Zahl ohne Kuerzel und ohne Nenner NICHT — "330 KP", "30 Jahre"
# und Jahreszahlen wuerden sonst als Kartennummer durchgehen.
# Beim Paar haengt das Kuerzel direkt an der Zahl ("SV085/SV122"). Ein
# Leerzeichen ist hier NICHT erlaubt: sonst liest "Glurak Holo 4/102" ein
# Kuerzel "HOLO" und verliert den Nenner.
_NUMBER_PAIR_RE = re.compile(
    r"\b([A-Z]{0,4})(\d{1,3})\s*/\s*([A-Z]{0,4})(\d{1,3})\b", re.IGNORECASE
)
# Ohne Nenner muss das Kuerzel GROSS geschrieben sein — so stehen echte
# Kartencodes auf der Karte (WHT 007, DP45, SWSH123, TG06). Das unterscheidet
# sie von gewoehnlichen Titelwoertern wie "Holo 45" oder "Lot 14".
_PROMO_NUMBER_RE = re.compile(r"\b([A-Z]{2,4})[\s-]?(\d{1,3})\b")

# Kuerzel, die zwar wie ein Kartencode aussehen, aber keiner sind. Ohne das
# liest der Resolver aus "Pokemon TCG Karten" ein "TCG" heraus.
_NOT_A_CARD_CODE = frozenset(
    {
        # Zustand, Sprache, Bewertung
        "NM", "LP", "MP", "HP", "PSA", "BGS", "CGC", "DE", "EN", "FR", "IT",
        "JP", "ED", "NR", "NO", "OVP", "TOP",
        # Spielbegriffe und Werbeworte, die zufaellig vor einer Zahl stehen
        "TCG", "KP", "EX", "GX", "VMAX", "HOLO", "FULL", "ART", "SET", "LOT",
        "NEU", "ALT", "MEGA", "RARE", "MINT", "NEAR", "USED", "PKM", "WOTC",
        "STK", "PCS", "EUR", "USD", "GBP",
    }
)


@dataclass(frozen=True)
class CardNumber:
    """Die Nummer aus dem Titel: Token wie im Titel, plus Nenner falls vorhanden."""

    token: str            # "4", "TG06", "WHT007"
    set_size: int | None  # 102 — nur wenn beide Seiten reine Zahlen sind
    printed: str          # so, wie es im Titel stand ("4/102", "WHT 007")


def extract_card_number(text: str) -> CardNumber | None:
    m = _NUMBER_PAIR_RE.search(text)
    if m:
        left_prefix, left, right_prefix, right = m.groups()
        token = f"{(left_prefix or '').upper()}{left}"
        # Der Nenner taugt nur dann zum Eingrenzen, wenn er die Set-Groesse ist.
        # Bei "SV085/SV122" ist er das nicht — die Shiny-Vault-Nummerierung
        # laeuft neben dem Hauptset her.
        set_size = int(right) if not left_prefix and not right_prefix else None
        return CardNumber(token=token, set_size=set_size, printed=m.group(0).strip())

    for m in _PROMO_NUMBER_RE.finditer(text):
        prefix, digits = m.groups()
        if prefix.upper() in _NOT_A_CARD_CODE:
            continue
        return CardNumber(
            token=f"{prefix.upper()}{digits}", set_size=None, printed=m.group(0).strip()
        )
    return None


def _split_code(value: str) -> tuple[str, str]:
    """"TG06" -> ("TG", "6"); "007" -> ("", "7")."""
    raw = re.sub(r"[\s\-_]", "", str(value)).upper()
    m = re.match(r"^([A-Z]*)(\d+)$", raw)
    if not m:
        return raw, ""
    letters, digits = m.groups()
    return letters, str(int(digits))


def numbers_match(card_local: object, wanted: str) -> bool:
    """Passt die Nummer der TCGdex-Karte zu der aus dem Titel?

    TCGdex fuehrt Promos mal als "SWSH123", mal nur als "123" — welche Form es
    ist, laesst sich von aussen nicht zuverlaessig sagen. Deshalb wird beides
    akzeptiert, aber nur in EINE Richtung: nennt der Titel ein Kuerzel und
    TCGdex nur die Zahl, gilt das als Treffer. Umgekehrt nicht — sonst wuerde
    "4/102" auf eine Trainer-Galerie-Karte "TG04" passen und einen falschen
    Wert erfinden.
    """
    c_letters, c_digits = _split_code(str(card_local))
    w_letters, w_digits = _split_code(wanted)
    if not c_digits or not w_digits:
        return str(card_local).strip().upper() == wanted.strip().upper()
    if c_digits != w_digits:
        return False
    if c_letters == w_letters:
        return True
    return bool(w_letters) and not c_letters

# Jubilee/anniversary reprints carry the ORIGINAL's numbering but are worth a
# fraction of it. Resolving "Turtok 2/102 ... Celebration 25. Jubiläum" to the
# 1999 Base Set card would invent a huge profit — exactly what R3 forbids. Such
# titles stay unbewertbar and go to the operator.
_REPRINT_SUBSTRINGS = ("celebration", "jubil", "classic collection", "anniversar")
_REPRINT_WORDS = re.compile(
    r"\b(?:promo|reprint|neudruck|nachdruck|replica|reprodukt)\b", re.IGNORECASE
)


# Nicht jedes Pokemon-Angebot ist eine Karte. Displays, Booster, Tins, Muenzen,
# Sleeves, sogar Game-Boy-Spiele laufen ueber dieselben Suchbegriffe mit. Die
# haben keine Kartennummer — und als "Karte nicht erkannt" zu zaehlen waere
# falsch: sie sind gar keine. Diese Pruefung greift NUR, wenn im Titel keine
# Kartennummer steht; "Glurak 4/102 aus Booster gezogen" bleibt eine Karte.
_PRODUCT_SUBSTRINGS = (
    "display", "booster", "elite trainer", "trainer box", "blister", "tin ",
    "sammelalbum", "portfolio", "toploader", "sleeve", "huelle", "hülle",
    "schutzhuelle", "schutzhülle", "muenze", "münze", "coin", "charm",
    "plüsch", "pluesch", "figur", "spielkonsole", "game boy", "gameboy",
    "nintendo", "poster", "sticker", "schluesselanhaenger", "schlüsselanhänger",
    "geldboerse", "geldbörse", "rucksack", "puzzle", "brettspiel",
)
_PRODUCT_WORDS = re.compile(
    r"\b(?:etb|tin|pack|packung|päckchen|paeckchen|box|boxen|tüte|tuete|"
    r"tüten|tueten|umschlag|umschläge|spiel|spiele|kissen|tasse)\b",
    re.IGNORECASE,
)


def looks_like_sealed_product(text: str) -> bool:
    low = text.lower()
    return any(h in low for h in _PRODUCT_SUBSTRINGS) or bool(
        _PRODUCT_WORDS.search(text)
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


def _name_in_title(card_name: str, low_title: str) -> bool:
    """Kommt der Kartenname im Titel vor?

    Verglichen wird ohne Zusaetze wie "-EX", "V" oder "VMAX": eBay-Titel
    schreiben "Turtok-EX", TCGdex fuehrt "Turtok ex". Ein Wortteil reicht
    NICHT — "Glurak" darf nicht auf "Glurak G Lv.X" passen, wenn beide Karten
    im Rennen sind.
    """
    name = card_name.strip().lower()
    if not name:
        return False
    if name in low_title:
        return True
    base = re.split(r"\s+(?:ex|gx|v|vmax|vstar|lv\.?x)\b", name, maxsplit=1)[0].strip()
    return bool(base) and len(base) >= 4 and base in low_title


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

        # Gate 1b: require a card number — one specific card slot.
        number = extract_card_number(text)
        if number is None:
            # Erst pruefen, ob das ueberhaupt eine Karte ist. "Kein Einzelkarten-
            # Angebot" und "Karte ohne Nummer im Titel" sind zwei verschiedene
            # Auskuenfte, und nur die zweite ist eine Luecke der Automatik.
            if looks_like_sealed_product(text):
                note(
                    "Tor 1b: kein Einzelkarten-Angebot (Zubehör oder versiegelte "
                    "Ware) -> unbewertbar"
                )
            else:
                note(
                    "Tor 1b: keine Kartennummer im Titel (z.B. 4/102, TG06/TG30, "
                    "DP45) -> unbewertbar"
                )
            return None
        local_id = number.token
        set_size = number.set_size
        note(f"Tor 1b: Kartennummer {number.printed} gefunden")

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
                        local := card_local_id(card)
                    ) is not None and numbers_match(local, local_id):
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
        if len(matches) > 1 and set_size is not None:
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

        # Mehrere Treffer heisst nicht automatisch "unbewertbar". Steht der Name
        # EINER dieser Karten im Titel und der der anderen nicht, ist der Fall
        # klar — der Titel nennt sie ja beim Namen. Das ist strenger als "ein
        # Suchwort hat zufaellig getroffen": gefordert wird der Kartenname
        # selbst. Ohne diesen Schritt warf die Suche nach drei Titelwoertern
        # ihre eigenen Nebentreffer als Mehrdeutigkeit wieder weg.
        if len(matches) > 1:
            by_name = {
                cid: c
                for cid, c in matches.items()
                if _name_in_title(str(c.get("name") or ""), low)
            }
            if len(by_name) == 1:
                note(
                    f"Tor 2: {len(matches)} Kandidaten — nur "
                    f"{next(iter(by_name.values())).get('name')} steht im Titel"
                )
                matches = by_name

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
            # Die Nummer fuer die spaetere Suche. Bei "4/102" bleibt der Nenner
            # dabei: eBay-Titel schreiben ihn mit, und die Verkaufssuche findet
            # damit deutlich mehr. Bei Promos gibt es keinen, da steht das
            # Kuerzel wie im Titel.
            number=(
                f"{_split_code(number.token)[1]}/{number.set_size}"
                if number.set_size is not None
                else number.printed.upper()
            ),
            language=language,
            printing=_printing_from_title(low),
        )
