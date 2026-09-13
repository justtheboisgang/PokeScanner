"""Deterministic text extraction of condition defects (§11) — pure, no LLM.

Scans title + description for defect keywords ("Knick", "bespielt", "Kratzer",
"gespielt", ...). These are HINTS for triage, never a condition verdict (§10).
"""

from __future__ import annotations

import re

# Canonical flag -> word/substring patterns (matched case-insensitively).
_DEFECT_PATTERNS: dict[str, tuple[str, ...]] = {
    "knick": ("knick", "geknickt", "knicke", "knicken"),
    "kratzer": ("kratzer", "verkratzt", "zerkratzt"),
    "bespielt": ("bespielt", "gespielt", "gebraucht", "abgegriffen"),
    "riss": ("riss", "eingerissen", "gerissen"),
    "delle": ("delle", "dellen", "eingedrückt"),
    "verblasst": ("verblasst", "ausgeblichen", "vergilbt", "verfärbt"),
    "wasserschaden": ("wasserschaden", "wasserflecken"),
    "fleck": ("fleck", "flecken", "fleckig", "verschmutzt"),
    "beschädigt": ("beschädigt", "beschaedigt", "schaden", "defekt"),
    "abnutzung": ("abnutzung", "abgenutzt", "gebrauchsspuren"),
    "verklebt": ("verklebt", "geklebt", "tesa", "kleber"),
}

# Precompiled word-ish patterns (substring with unicode-aware boundaries).
_COMPILED: dict[str, re.Pattern] = {
    flag: re.compile("|".join(re.escape(p) for p in patterns), re.IGNORECASE)
    for flag, patterns in _DEFECT_PATTERNS.items()
}


def extract_condition_flags(*texts: str | None) -> list[str]:
    """Return the sorted canonical defect flags found across the given texts."""
    haystack = " ".join(t for t in texts if t)
    if not haystack:
        return []
    found = [flag for flag, pattern in _COMPILED.items() if pattern.search(haystack)]
    return sorted(found)
