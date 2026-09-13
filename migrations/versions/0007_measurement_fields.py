"""measurement fields: triggering terms, listed_at, time_to_alert (Block 1)

Revision ID: 0007_measurement_fields
Revises: 0006_api_cost
Create Date: 2026-09-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_measurement_fields"
down_revision = "0006_api_cost"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate",
        sa.Column(
            "triggering_search_terms",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "candidate", sa.Column("time_to_alert_seconds", sa.Integer(), nullable=True)
    )
    op.add_column(
        "listing", sa.Column("listed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "listing", sa.Column("listed_at_precision", sa.String(16), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("listing", "listed_at_precision")
    op.drop_column("listing", "listed_at")
    op.drop_column("candidate", "time_to_alert_seconds")
    op.drop_column("candidate", "triggering_search_terms")
