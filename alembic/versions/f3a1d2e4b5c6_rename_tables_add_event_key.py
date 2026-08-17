"""rename raw/transformed tables and add event_key column

Revision ID: f3a1d2e4b5c6
Revises: a2a4bb6970ed
Create Date: 2026-08-17

Renames:
  raw_extract           → facebook_listing_raw
  transformed           → facebook_listing_transformed

Adds:
  event_key VARCHAR(64) NOT NULL to both tables,
  backfilled from the events table via event_id.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f3a1d2e4b5c6'
down_revision: Union[str, None] = '700c170a1526'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Rename tables ──────────────────────────────────────────────────────
    op.rename_table('raw_extract', 'facebook_listing_raw')
    op.rename_table('transformed', 'facebook_listing_transformed')

    # ── 2. Add event_key columns (nullable first so existing rows are accepted)
    op.add_column('facebook_listing_raw',
        sa.Column('event_key', sa.String(64), nullable=True))
    op.add_column('facebook_listing_transformed',
        sa.Column('event_key', sa.String(64), nullable=True))

    # ── 3. Backfill event_key from the events table via event_id ──────────────
    op.execute("""
        UPDATE facebook_listing_raw r
        SET event_key = e.event_key
        FROM events e
        WHERE r.event_id = e.id
    """)
    op.execute("""
        UPDATE facebook_listing_transformed t
        SET event_key = e.event_key
        FROM events e
        WHERE t.event_id = e.id
    """)

    # ── 4. Enforce NOT NULL now that all rows are backfilled ──────────────────
    op.alter_column('facebook_listing_raw', 'event_key', nullable=False)
    op.alter_column('facebook_listing_transformed', 'event_key', nullable=False)


def downgrade() -> None:
    # Reverse: drop event_key, rename tables back
    op.alter_column('facebook_listing_transformed', 'event_key', nullable=True)
    op.alter_column('facebook_listing_raw', 'event_key', nullable=True)

    op.drop_column('facebook_listing_transformed', 'event_key')
    op.drop_column('facebook_listing_raw', 'event_key')

    op.rename_table('facebook_listing_transformed', 'transformed')
    op.rename_table('facebook_listing_raw', 'raw_extract')
