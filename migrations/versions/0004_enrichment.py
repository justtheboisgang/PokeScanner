"""enrichment: post-alarm advisory hints (§10/§11)

Revision ID: 0004_enrichment
Revises: 0003_reference_comp
Create Date: 2026-09-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_enrichment"
down_revision = "0003_reference_comp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enrichment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidate.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "condition_flags",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("vision_summary", sa.Text(), nullable=True),
        sa.Column("vision_model", sa.String(64), nullable=True),
        sa.Column(
            "vision_used", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "enriched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("candidate_id", name="uq_enrichment_candidate"),
    )
    op.create_index("ix_enrichment_candidate_id", "enrichment", ["candidate_id"])


def downgrade() -> None:
    op.drop_index("ix_enrichment_candidate_id", table_name="enrichment")
    op.drop_table("enrichment")
