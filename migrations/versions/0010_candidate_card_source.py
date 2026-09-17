"""candidate_card.source: Handarbeit von Automatik unterscheiden

Revision ID: 0010_candidate_card_source
Revises: 0009_market_snapshot
Create Date: 2026-09-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_candidate_card_source"
down_revision = "0009_market_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate_card",
        sa.Column(
            "source", sa.String(16), server_default="manual", nullable=False
        ),
    )
    # Bestandsdaten: Zeilen ohne Referenzwert stammen aus abgebrochenen
    # Automatik-Versuchen (die Kaskade legt den Link an, bevor sie bewertet).
    # Sie als "auto" zu markieren gibt sie zur Wiederholung frei; Zeilen MIT
    # Referenzwert bleiben unangetastet.
    op.execute(
        "UPDATE candidate_card SET source = 'auto' WHERE reference_value_id IS NULL"
    )


def downgrade() -> None:
    op.drop_column("candidate_card", "source")
