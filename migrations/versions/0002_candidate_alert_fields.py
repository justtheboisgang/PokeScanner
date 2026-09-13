"""candidate: matched_search_term + discord_message_id

Revision ID: 0002_candidate_alert_fields
Revises: 0001_initial
Create Date: 2026-09-13

Phase 2: record the triggering taxonomy term per candidate (for data-driven query
rotation, §4.4) and the Discord message id (so enrichment can edit the embed, §8).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_candidate_alert_fields"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate",
        sa.Column("matched_search_term", sa.String(255), nullable=True),
    )
    op.add_column(
        "candidate",
        sa.Column("discord_message_id", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_candidate_matched_search_term", "candidate", ["matched_search_term"]
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_matched_search_term", table_name="candidate")
    op.drop_column("candidate", "discord_message_id")
    op.drop_column("candidate", "matched_search_term")
