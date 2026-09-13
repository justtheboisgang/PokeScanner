"""reference_comp: individual comps behind a reference value (§9)

Revision ID: 0003_reference_comp
Revises: 0002_candidate_alert_fields
Create Date: 2026-09-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.enums import Condition, Language
from app.models.sa_types import enum_type

revision = "0003_reference_comp"
down_revision = "0002_candidate_alert_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reference_comp",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "reference_value_id",
            sa.Integer(),
            sa.ForeignKey("reference_value.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="EUR", nullable=False),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("language", enum_type(Language, "language"), nullable=False),
        sa.Column("condition", enum_type(Condition, "condition"), nullable=False),
        sa.Column(
            "boa_hydrated", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("epid", sa.String(64), nullable=True),
        sa.Column("source_item_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_reference_comp_reference_value_id",
        "reference_comp",
        ["reference_value_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reference_comp_reference_value_id", table_name="reference_comp"
    )
    op.drop_table("reference_comp")
