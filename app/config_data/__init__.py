"""Runtime-editable config data (search-term taxonomy, ...)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_SEARCH_TERMS_PATH = Path(__file__).with_name("search_terms.yaml")


@dataclass(frozen=True)
class SearchTerms:
    positive: tuple[str, ...]
    negative: tuple[str, ...]
    # Curated subset actually queried per poll (§4.4). Falls back to `positive`.
    active: tuple[str, ...]

    def is_excluded(self, text: str) -> bool:
        """True if any negative term appears in the given text (case-insensitive)."""
        low = text.lower()
        return any(neg in low for neg in self.negative)


def load_search_terms(path: Path | None = None) -> SearchTerms:
    """Load the search-term taxonomy from YAML (§7)."""
    data = yaml.safe_load((path or _SEARCH_TERMS_PATH).read_text(encoding="utf-8"))
    data = data or {}
    positive = tuple(str(t) for t in (data.get("positive") or []))
    negative = tuple(str(t).lower() for t in (data.get("negative") or []))
    active = tuple(str(t) for t in (data.get("active") or [])) or positive
    return SearchTerms(positive=positive, negative=negative, active=active)
