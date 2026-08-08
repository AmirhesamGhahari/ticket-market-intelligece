"""Create veld_2026 tables: veld_2026_raw_extract (Bronze) and veld_2026_transformed (Silver).

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-07-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "b2c3d4e5f6a1"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── veld_2026_raw_extract (Bronze / raw ingestion with CDC) ───────────────
    op.create_table(
        "veld_2026_raw_extract",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("pipeline_run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("fb_listing_id", sa.Text, nullable=False),
        sa.Column("listing_url", sa.Text, nullable=False),
        sa.Column("seller_profile_id", sa.Text, nullable=True),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("location_city", sa.Text, nullable=True),
        sa.Column("location_state", sa.Text, nullable=True),
        sa.Column("image_urls", JSONB, nullable=True),
        sa.Column("is_sold", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("listed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_payload", JSONB, nullable=False),
        # CDC columns — valid_to IS NULL means this is the current version
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["pipeline_run_id"],
            ["pipeline_runs.id"],
            name="fk_veld_2026_raw_run_id",
        ),
    )

    op.create_index("idx_veld_2026_raw_fb_listing_id", "veld_2026_raw_extract", ["fb_listing_id"])
    op.create_index("idx_veld_2026_raw_listed_at", "veld_2026_raw_extract", ["listed_at"])
    op.create_index("idx_veld_2026_raw_run", "veld_2026_raw_extract", ["pipeline_run_id"])
    # Partial index for fast current-record lookups (WHERE valid_to IS NULL)
    op.create_index(
        "idx_veld_2026_raw_current_url",
        "veld_2026_raw_extract",
        ["listing_url"],
        postgresql_where="valid_to IS NULL",
    )

    # ── veld_2026_transformed (Silver / enriched) ─────────────────────────────
    # Must come after veld_2026_raw_extract because of the FK on raw_id.
    op.create_table(
        "veld_2026_transformed",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("raw_id", sa.BigInteger, nullable=False),
        sa.Column("pipeline_run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("fb_listing_id", sa.Text, nullable=False),
        sa.Column("listing_url", sa.Text, nullable=False),
        sa.Column("seller_profile_id", sa.Text, nullable=True),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("currency", sa.String(10), nullable=False, server_default="CAD"),
        sa.Column("is_sold", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("listed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("image_urls", JSONB, nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("price_per_unit", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "price_is_anomaly", sa.Boolean, nullable=False, server_default="false"
        ),
        sa.Column("location_city", sa.Text, nullable=True),
        sa.Column("location_state", sa.String(10), nullable=True),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "ticket_type", sa.String(32), nullable=False, server_default="UNKNOWN"
        ),
        sa.Column("event_days", JSONB, nullable=True),
        sa.Column(
            "listing_type", sa.String(32), nullable=False, server_default="resale"
        ),
        sa.Column("is_relevant", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_id"],
            ["veld_2026_raw_extract.id"],
            name="fk_veld_2026_transformed_raw_id",
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_run_id"],
            ["pipeline_runs.id"],
            name="fk_veld_2026_transformed_run_id",
        ),
        sa.UniqueConstraint("raw_id", name="uq_veld_2026_transformed_raw_id"),
    )

    op.create_index("idx_veld_2026_transformed_location_city", "veld_2026_transformed", ["location_city"])
    op.create_index("idx_veld_2026_transformed_price", "veld_2026_transformed", ["price"])
    op.create_index("idx_veld_2026_transformed_listed_at", "veld_2026_transformed", ["listed_at"])
    op.create_index("idx_veld_2026_transformed_listing_id", "veld_2026_transformed", ["fb_listing_id"])
    op.create_index("idx_veld_2026_transformed_seller", "veld_2026_transformed", ["seller_profile_id"])
    op.create_index("idx_veld_2026_transformed_pipeline_run", "veld_2026_transformed", ["pipeline_run_id"])


def downgrade() -> None:
    op.drop_table("veld_2026_transformed")
    op.drop_table("veld_2026_raw_extract")
