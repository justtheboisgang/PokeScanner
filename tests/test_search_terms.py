"""Search-term taxonomy loader (§7)."""

from __future__ import annotations

from app.config_data import load_search_terms


def test_loads_positive_and_negative_terms():
    st = load_search_terms()
    assert len(st.positive) >= 50  # §7 asks for 50-100
    assert "alte pokemon karten" in st.positive
    assert st.negative  # non-empty


def test_negative_exclusion_is_case_insensitive():
    st = load_search_terms()
    assert st.is_excluded("Tolle PSA 10 Glurak") is True  # graded excluded (§10)
    assert st.is_excluded("Repro Charizard") is True
    assert st.is_excluded("Alte Pokemon Sammlung vom Dachboden") is False
