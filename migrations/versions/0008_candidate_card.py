"""candidate_card: manual card identifications (Block 2.3)

Revision ID: 0008_candidate_card
Revises: 0007_measurement_fields
Create Date: 2026-09-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_candidate_card"
down_revision = "0007_measurement_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_card",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidate.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
        sa.Column("quantity", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_candidate_card_candidate_id", "candidate_card", ["candidate_id"])


def downgrade() -> None:
    op.drop_index("ix_candidate_card_candidate_id", table_name="candidate_card")
    op.drop_table("candidate_card")
