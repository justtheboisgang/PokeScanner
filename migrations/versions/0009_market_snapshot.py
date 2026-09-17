"""market_snapshot: Marktpreise neben dem echten Verkaufswert

Revision ID: 0009_market_snapshot
Revises: 0008_candidate_card
Create Date: 2026-09-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_market_snapshot"
down_revision = "0008_candidate_card"
branch_labels = None
depends_on = None

_MONEY = sa.Numeric(12, 2)


def upgrade() -> None:
    op.create_table(
        "market_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "variant_id",
            sa.Integer(),
            sa.ForeignKey("variant.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reference_value_id",
            sa.Integer(),
            sa.ForeignKey("reference_value.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Cardmarket (EUR)
        sa.Column("cm_avg", _MONEY, nullable=True),
        sa.Column("cm_low", _MONEY, nullable=True),
        sa.Column("cm_trend", _MONEY, nullable=True),
        sa.Column("cm_avg7", _MONEY, nullable=True),
        sa.Column("cm_avg30", _MONEY, nullable=True),
        # TCGPlayer (USD) — never converted.
        sa.Column("tcg_market_usd", _MONEY, nullable=True),
        sa.Column("tcg_low_usd", _MONEY, nullable=True),
        sa.Column("source", sa.String(32), server_default="pokewallet", nullable=False),
        sa.Column("source_card_id", sa.String(128), nullable=True),
        sa.Column("variant_label", sa.String(32), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_market_snapshot_variant_id", "market_snapshot", ["variant_id"])
    op.create_index(
        "ix_market_snapshot_reference_value_id", "market_snapshot", ["reference_value_id"]
    )
    op.create_index("ix_market_snapshot_captured_at", "market_snapshot", ["captured_at"])


def downgrade() -> None:
    op.drop_index("ix_market_snapshot_captured_at", table_name="market_snapshot")
    op.drop_index("ix_market_snapshot_reference_value_id", table_name="market_snapshot")
    op.drop_index("ix_market_snapshot_variant_id", table_name="market_snapshot")
    op.drop_table("market_snapshot")
