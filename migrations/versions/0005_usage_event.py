"""usage_event: API call counts per source (§9 Kosten)

Revision ID: 0005_usage_event
Revises: 0004_enrichment
Create Date: 2026-09-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_usage_event"
down_revision = "0004_enrichment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_usage_event_source", "usage_event", ["source"])
    op.create_index("ix_usage_event_recorded_at", "usage_event", ["recorded_at"])


def downgrade() -> None:
    op.drop_index("ix_usage_event_recorded_at", table_name="usage_event")
    op.drop_index("ix_usage_event_source", table_name="usage_event")
    op.drop_table("usage_event")
