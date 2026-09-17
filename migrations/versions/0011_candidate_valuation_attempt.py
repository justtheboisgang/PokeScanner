"""candidate: Bewertungsversuch festhalten (ob und woran gescheitert)

"unbewertbar" bedeutete zweierlei — geprueft und nichts gefunden, oder nie
angefasst. Der Betreiber konnte beides nicht unterscheiden und fragte zu Recht
immer wieder, warum "alles unbewertbar" ist. Diese zwei Spalten trennen das.

Revision ID: 0011_candidate_valuation_attempt
Revises: 0010_candidate_card_source
Create Date: 2026-09-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_candidate_valuation_attempt"
down_revision = "0010_candidate_card_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate",
        sa.Column("valuation_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "candidate", sa.Column("valuation_note", sa.String(200), nullable=True)
    )
    # Bestandsdaten bleiben NULL: fuer alte Kandidaten ist nicht rekonstruierbar,
    # ob je ein Versuch lief. NULL heisst in der Oberflaeche genau das —
    # "noch nicht bewertet" — und das ist die ehrliche Auskunft. Wer schon einen
    # Referenzwert hat, wird ohnehin nicht als unbewertbar angezeigt.


def downgrade() -> None:
    op.drop_column("candidate", "valuation_note")
    op.drop_column("candidate", "valuation_attempted_at")
