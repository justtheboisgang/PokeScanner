"""auction_watch: Auktionen, die bald enden

Revision ID: 0012_auction_watch
Revises: 0011_candidate_valuation_attempt
Create Date: 2026-09-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_auction_watch"
down_revision = "0011_candidate_valuation_attempt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auction_watch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("url", sa.String(1000)),
        sa.Column("image", sa.String(1000)),
        sa.Column("currency", sa.String(8), server_default="EUR", nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_price", sa.Numeric(12, 2)),
        sa.Column("reference_value_eur", sa.Numeric(12, 2)),
        sa.Column("reference_source", sa.String(32)),
        sa.Column("card_name", sa.String(200)),
        sa.Column("card_number", sa.String(32)),
        sa.Column("skip_reason", sa.String(200)),
        sa.Column("matched_search_term", sa.String(255)),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("alerted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("external_id", name="uq_auction_watch_external"),
    )
    op.create_index("ix_auction_watch_external_id", "auction_watch", ["external_id"])
    op.create_index("ix_auction_watch_ends_at", "auction_watch", ["ends_at"])


def downgrade() -> None:
    op.drop_index("ix_auction_watch_ends_at", table_name="auction_watch")
    op.drop_index("ix_auction_watch_external_id", table_name="auction_watch")
    op.drop_table("auction_watch")
