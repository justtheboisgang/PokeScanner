"""api_cost: per-call cost ledger (Block 0.2 Cost Guard)

Revision ID: 0006_api_cost
Revises: 0005_usage_event
Create Date: 2026-09-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_api_cost"
down_revision = "0005_usage_event"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_cost",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("endpoint", sa.String(128), nullable=False),
        sa.Column("units", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "estimated_cost_eur",
            sa.Numeric(12, 4),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidate.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_api_cost_provider", "api_cost", ["provider"])
    op.create_index("ix_api_cost_created_at", "api_cost", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_api_cost_created_at", table_name="api_cost")
    op.drop_index("ix_api_cost_provider", table_name="api_cost")
    op.drop_table("api_cost")
