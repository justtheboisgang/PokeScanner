"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-12

Rohdaten / berechnete Werte / Urteile strikt getrennt (§5).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.enums import (
    Channel,
    Condition,
    CounterfeitCheck,
    Language,
    Printing,
    ReferenceSource,
    SellerType,
    Verdict,
)
from app.models.sa_types import enum_type

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "card",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("set", sa.String(255), nullable=True),
        sa.Column("number", sa.String(64), nullable=True),
        sa.Column("era", sa.String(64), nullable=True),
        sa.Column("tcgdex_id", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("tcgdex_id", name="uq_card_tcgdex_id"),
    )
    op.create_index("ix_card_name", "card", ["name"])
    op.create_index("ix_card_era", "card", ["era"])
    op.create_index("ix_card_tcgdex_id", "card", ["tcgdex_id"])

    op.create_table(
        "variant",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "card_id",
            sa.Integer(),
            sa.ForeignKey("card.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "language",
            enum_type(Language, "language"),
            server_default=Language.DE.value,
            nullable=False,
        ),
        sa.Column(
            "condition",
            enum_type(Condition, "condition"),
            server_default=Condition.PLAYED.value,
            nullable=False,
        ),
        sa.Column(
            "printing",
            enum_type(Printing, "printing"),
            server_default=Printing.UNKNOWN.value,
            nullable=False,
        ),
        sa.UniqueConstraint(
            "card_id", "language", "condition", "printing", name="uq_variant_identity"
        ),
    )
    op.create_index("ix_variant_card_id", "variant", ["card_id"])

    op.create_table(
        "listing",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel", enum_type(Channel, "channel"), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(3), server_default="EUR", nullable=False),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column(
            "seller_type",
            enum_type(SellerType, "sellertype"),
            server_default=SellerType.UNKNOWN.value,
            nullable=False,
        ),
        sa.Column(
            "images",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("image_hash", sa.String(64), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "channel", "external_id", name="uq_listing_channel_external"
        ),
    )
    op.create_index("ix_listing_channel", "listing", ["channel"])
    op.create_index("ix_listing_external_id", "listing", ["external_id"])
    op.create_index("ix_listing_image_hash", "listing", ["image_hash"])

    op.create_table(
        "reference_value",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "variant_id",
            sa.Integer(),
            sa.ForeignKey("variant.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="EUR", nullable=False),
        sa.Column(
            "source", enum_type(ReferenceSource, "referencesource"), nullable=False
        ),
        sa.Column("cascade_level", sa.Integer(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column(
            "is_weak", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_reference_value_variant_id", "reference_value", ["variant_id"])

    op.create_table(
        "candidate",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "listing_id",
            sa.Integer(),
            sa.ForeignKey("listing.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reference_value_id",
            sa.Integer(),
            sa.ForeignKey("reference_value.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("estimated_profit", sa.Numeric(12, 2), nullable=True),
        sa.Column("alert_reason", sa.Text(), nullable=True),
        sa.Column("alert_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_candidate_listing_id", "candidate", ["listing_id"])

    op.create_table(
        "decision",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidate.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("verdict", enum_type(Verdict, "verdict"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "counterfeit_check",
            enum_type(CounterfeitCheck, "counterfeitcheck"),
            server_default=CounterfeitCheck.NOT_CHECKED.value,
            nullable=False,
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("seconds_since_alert", sa.Integer(), nullable=True),
        sa.UniqueConstraint("candidate_id", name="uq_decision_candidate"),
    )
    op.create_index("ix_decision_candidate_id", "decision", ["candidate_id"])

    op.create_table(
        "purchase",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidate.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # §25a UStG mandatory fields — NOT NULL.
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("channel", enum_type(Channel, "channel"), nullable=False),
        sa.Column("seller_name", sa.String(255), nullable=False),
        sa.Column("seller_address", sa.Text(), nullable=False),
        sa.Column(
            "shipping_cost",
            sa.Numeric(12, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("currency", sa.String(3), server_default="EUR", nullable=False),
    )

    op.create_table(
        "sale",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "purchase_id",
            sa.Integer(),
            sa.ForeignKey("purchase.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("channel", enum_type(Channel, "channel"), nullable=False),
        sa.Column("fees", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("days_to_sell", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(3), server_default="EUR", nullable=False),
        sa.UniqueConstraint("purchase_id", name="uq_sale_purchase"),
    )
    op.create_index("ix_sale_purchase_id", "sale", ["purchase_id"])


def downgrade() -> None:
    op.drop_table("sale")
    op.drop_table("purchase")
    op.drop_index("ix_decision_candidate_id", table_name="decision")
    op.drop_table("decision")
    op.drop_index("ix_candidate_listing_id", table_name="candidate")
    op.drop_table("candidate")
    op.drop_index("ix_reference_value_variant_id", table_name="reference_value")
    op.drop_table("reference_value")
    op.drop_index("ix_listing_image_hash", table_name="listing")
    op.drop_index("ix_listing_external_id", table_name="listing")
    op.drop_index("ix_listing_channel", table_name="listing")
    op.drop_table("listing")
    op.drop_index("ix_variant_card_id", table_name="variant")
    op.drop_table("variant")
    op.drop_index("ix_card_tcgdex_id", table_name="card")
    op.drop_index("ix_card_era", table_name="card")
    op.drop_index("ix_card_name", table_name="card")
    op.drop_table("card")
