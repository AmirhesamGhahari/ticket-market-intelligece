"""Move and rename legacy Facebook tables into the facebook schema.

Revision ID: c1d2e3f4a5b6
Revises: 3e833675849f
Create Date: 2026-09-17 00:00:00.000000

Moves public.facebook_listing_raw and public.facebook_listing_classifications
into the facebook schema and renames them to facebook_listings_legacy_raw and
facebook_listings_legacy_classified respectively.

This is a manual migration because Alembic autogenerate cannot detect renames.
Run this BEFORE running alembic revision --autogenerate for the new tables.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = '3e833675849f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Create the facebook schema ─────────────────────────────────────────
    op.execute("CREATE SCHEMA IF NOT EXISTS facebook")

    # ── 2. Drop the FK between the two tables before moving them ──────────────
    # The FK references facebook_listing_raw.id. Moving tables across schemas
    # while an inter-table FK is active can confuse PostgreSQL's constraint
    # resolution. Drop it now and recreate after renaming.
    op.drop_constraint(
        'fk_fb_classification_raw',
        'facebook_listing_classifications',
        type_='foreignkey',
    )

    # ── 3. Move both tables into the facebook schema ───────────────────────────
    op.execute("ALTER TABLE public.facebook_listing_raw SET SCHEMA facebook")
    op.execute("ALTER TABLE public.facebook_listing_classifications SET SCHEMA facebook")

    # ── 4. Rename both tables ─────────────────────────────────────────────────
    op.execute(
        "ALTER TABLE facebook.facebook_listing_raw "
        "RENAME TO facebook_listings_legacy_raw"
    )
    op.execute(
        "ALTER TABLE facebook.facebook_listing_classifications "
        "RENAME TO facebook_listings_legacy_classified"
    )

    # ── 5. Recreate the inter-table FK with an updated name ───────────────────
    op.create_foreign_key(
        'fk_fb_legacy_classified_raw',
        'facebook_listings_legacy_classified',
        'facebook_listings_legacy_raw',
        ['raw_listing_id'], ['id'],
        source_schema='facebook',
        referent_schema='facebook',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_fb_legacy_classified_raw',
        'facebook_listings_legacy_classified',
        schema='facebook',
        type_='foreignkey',
    )

    op.execute(
        "ALTER TABLE facebook.facebook_listings_legacy_classified "
        "RENAME TO facebook_listing_classifications"
    )
    op.execute(
        "ALTER TABLE facebook.facebook_listings_legacy_raw "
        "RENAME TO facebook_listing_raw"
    )

    op.execute("ALTER TABLE facebook.facebook_listing_raw SET SCHEMA public")
    op.execute("ALTER TABLE facebook.facebook_listing_classifications SET SCHEMA public")

    op.create_foreign_key(
        'fk_fb_classification_raw',
        'facebook_listing_classifications',
        'facebook_listing_raw',
        ['raw_listing_id'], ['id'],
    )

    op.execute("DROP SCHEMA IF EXISTS facebook")
