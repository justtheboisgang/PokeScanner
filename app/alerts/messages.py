"""Pre-formulated contact message (§8).

Personal, not generic — im C2C sucht sich der Verkäufer den Käufer aus, eine
Bot-Nachricht wird ignoriert. Copied by hand by the operator; never auto-sent (§10).
"""

from __future__ import annotations

_CONTACT_TEMPLATE = (
    "Hallo! Ist die Sammlung noch verfügbar? Ich sammle selbst und hätte "
    "großes Interesse. Ich könnte kurzfristig — gern noch heute — vorbeikommen "
    "und bar bezahlen. Viele Grüße"
)


def contact_message() -> str:
    """Return the copy-ready contact message."""
    return _CONTACT_TEMPLATE
