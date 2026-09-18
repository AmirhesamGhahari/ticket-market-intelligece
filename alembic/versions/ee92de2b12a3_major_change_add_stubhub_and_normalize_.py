"""major change add stubhub and normalize facebook source

Revision ID: ee92de2b12a3
Revises: c4be2cbbc890
Create Date: 2026-09-17 23:27:19.991255

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'ee92de2b12a3'
down_revision: Union[str, None] = 'c4be2cbbc890'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create stubhub schema (facebook schema already exists from c1d2e3f4a5b6)
    op.execute("CREATE SCHEMA IF NOT EXISTS stubhub")

    # New Facebook listings (futurafree actor)
    op.create_table('facebook_listings_new_raw',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('event_id', sa.UUID(), nullable=False),
    sa.Column('event_key', sa.String(length=64), nullable=False),
    sa.Column('pipeline_run_id', sa.UUID(), nullable=False),
    sa.Column('fb_listing_id', sa.Text(), nullable=False),
    sa.Column('listing_url', sa.Text(), nullable=True),
    sa.Column('seller_id', sa.Text(), nullable=True),
    sa.Column('seller_name', sa.Text(), nullable=True),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('price', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('currency', sa.String(length=10), nullable=True),
    sa.Column('location_city', sa.Text(), nullable=True),
    sa.Column('location_state', sa.Text(), nullable=True),
    sa.Column('image_urls', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('is_sold', sa.Boolean(), nullable=False),
    sa.Column('is_pending', sa.Boolean(), nullable=False),
    sa.Column('listed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('scraped_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('raw_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['event_id'], ['public.events.id'], name='fk_fb_mkt_listing_raw_event_id'),
    sa.ForeignKeyConstraint(['pipeline_run_id'], ['public.pipeline_runs.id'], name='fk_fb_mkt_listing_raw_run_id'),
    sa.PrimaryKeyConstraint('id'),
    schema='facebook'
    )
    op.create_index('idx_fb_mkt_listing_raw_current_listing', 'facebook_listings_new_raw', ['event_id', 'fb_listing_id'], unique=True, schema='facebook', postgresql_where=sa.text('valid_to IS NULL'))
    op.create_index('idx_fb_mkt_listing_raw_event_listed_at', 'facebook_listings_new_raw', ['event_id', 'listed_at'], unique=False, schema='facebook')
    op.create_index('idx_fb_mkt_listing_raw_event_listing', 'facebook_listings_new_raw', ['event_id', 'fb_listing_id'], unique=False, schema='facebook')
    op.create_index('idx_fb_mkt_listing_raw_run', 'facebook_listings_new_raw', ['pipeline_run_id'], unique=False, schema='facebook')

    # StubHub listings
    op.create_table('listing_raw',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('event_id', sa.UUID(), nullable=False),
    sa.Column('event_key', sa.String(length=64), nullable=False),
    sa.Column('pipeline_run_id', sa.UUID(), nullable=False),
    sa.Column('listing_id', sa.Text(), nullable=False),
    sa.Column('section', sa.Text(), nullable=True),
    sa.Column('ticket_class', sa.Text(), nullable=True),
    sa.Column('row', sa.Text(), nullable=True),
    sa.Column('seat_from', sa.Integer(), nullable=True),
    sa.Column('seat_to', sa.Integer(), nullable=True),
    sa.Column('available_tickets', sa.Integer(), nullable=True),
    sa.Column('available_quantities', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('raw_price', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('display_price', sa.Text(), nullable=True),
    sa.Column('total_price', sa.Text(), nullable=True),
    sa.Column('currency', sa.String(length=10), nullable=True),
    sa.Column('face_value', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('face_value_currency', sa.String(length=10), nullable=True),
    sa.Column('ticket_type', sa.Text(), nullable=True),
    sa.Column('deal_score', sa.Text(), nullable=True),
    sa.Column('star_rating', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('listing_notes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('is_cheapest', sa.Boolean(), nullable=True),
    sa.Column('is_sponsored', sa.Boolean(), nullable=True),
    sa.Column('stubhub_created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('scraped_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('raw_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['event_id'], ['public.events.id'], name='fk_sh_listing_raw_event_id'),
    sa.ForeignKeyConstraint(['pipeline_run_id'], ['public.pipeline_runs.id'], name='fk_sh_listing_raw_run_id'),
    sa.PrimaryKeyConstraint('id'),
    schema='stubhub'
    )
    op.create_index('idx_sh_listing_raw_current_listing', 'listing_raw', ['event_id', 'listing_id'], unique=True, schema='stubhub', postgresql_where=sa.text('valid_to IS NULL'))
    op.create_index('idx_sh_listing_raw_event_listing', 'listing_raw', ['event_id', 'listing_id'], unique=False, schema='stubhub')
    op.create_index('idx_sh_listing_raw_event_price', 'listing_raw', ['event_id', 'raw_price'], unique=False, schema='stubhub')
    op.create_index('idx_sh_listing_raw_run', 'listing_raw', ['pipeline_run_id'], unique=False, schema='stubhub')

    # New Facebook classified (depends on facebook_listings_new_raw)
    op.create_table('facebook_listings_new_classified',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('raw_listing_id', sa.BigInteger(), nullable=False),
    sa.Column('classified_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('llm_model', sa.Text(), nullable=False),
    sa.Column('is_ticket', sa.Boolean(), nullable=False),
    sa.Column('is_buyer_listing', sa.Boolean(), nullable=False),
    sa.Column('is_merch', sa.Boolean(), nullable=False),
    sa.Column('is_wrong_category', sa.Boolean(), nullable=False),
    sa.Column('extracted_event', sa.Text(), nullable=True),
    sa.Column('extracted_price', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('face_value_price', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('face_value_mentioned', sa.Boolean(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=True),
    sa.Column('ticket_type', sa.String(length=30), nullable=True),
    sa.Column('event_days', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('price_negotiable', sa.Boolean(), nullable=False),
    sa.Column('includes_extras', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('seller_note', sa.Text(), nullable=True),
    sa.Column('confidence', sa.String(length=10), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('raw_llm_response', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['raw_listing_id'], ['facebook.facebook_listings_new_raw.id'], name='fk_fb_mkt_classified_raw'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('raw_listing_id', name='uq_fb_mkt_classified_raw_listing'),
    schema='facebook'
    )
    op.create_index('idx_fb_mkt_classified_classified_at', 'facebook_listings_new_classified', ['classified_at'], unique=False, schema='facebook')
    op.create_index('idx_fb_mkt_classified_is_ticket', 'facebook_listings_new_classified', ['is_ticket'], unique=False, schema='facebook')
    op.create_index('idx_fb_mkt_classified_raw_listing_id', 'facebook_listings_new_classified', ['raw_listing_id'], unique=False, schema='facebook')

    # Rename FK constraints on legacy raw table to match current model names
    # (old names were set before the table was moved to the facebook schema)
    op.drop_constraint('fk_raw_extract_event_id', 'facebook_listings_legacy_raw', schema='facebook', type_='foreignkey')
    op.drop_constraint('fk_raw_extract_run_id', 'facebook_listings_legacy_raw', schema='facebook', type_='foreignkey')
    op.create_foreign_key('fk_fb_listing_raw_event_id', 'facebook_listings_legacy_raw', 'events', ['event_id'], ['id'], source_schema='facebook', referent_schema='public')
    op.create_foreign_key('fk_fb_listing_raw_run_id', 'facebook_listings_legacy_raw', 'pipeline_runs', ['pipeline_run_id'], ['id'], source_schema='facebook', referent_schema='public')


def downgrade() -> None:
    op.drop_constraint('fk_fb_listing_raw_run_id', 'facebook_listings_legacy_raw', schema='facebook', type_='foreignkey')
    op.drop_constraint('fk_fb_listing_raw_event_id', 'facebook_listings_legacy_raw', schema='facebook', type_='foreignkey')
    op.create_foreign_key('fk_raw_extract_run_id', 'facebook_listings_legacy_raw', 'pipeline_runs', ['pipeline_run_id'], ['id'], source_schema='facebook')
    op.create_foreign_key('fk_raw_extract_event_id', 'facebook_listings_legacy_raw', 'events', ['event_id'], ['id'], source_schema='facebook')

    op.drop_index('idx_fb_mkt_classified_raw_listing_id', table_name='facebook_listings_new_classified', schema='facebook')
    op.drop_index('idx_fb_mkt_classified_is_ticket', table_name='facebook_listings_new_classified', schema='facebook')
    op.drop_index('idx_fb_mkt_classified_classified_at', table_name='facebook_listings_new_classified', schema='facebook')
    op.drop_table('facebook_listings_new_classified', schema='facebook')

    op.drop_index('idx_sh_listing_raw_run', table_name='listing_raw', schema='stubhub')
    op.drop_index('idx_sh_listing_raw_event_price', table_name='listing_raw', schema='stubhub')
    op.drop_index('idx_sh_listing_raw_event_listing', table_name='listing_raw', schema='stubhub')
    op.drop_index('idx_sh_listing_raw_current_listing', table_name='listing_raw', schema='stubhub', postgresql_where=sa.text('valid_to IS NULL'))
    op.drop_table('listing_raw', schema='stubhub')

    op.drop_index('idx_fb_mkt_listing_raw_run', table_name='facebook_listings_new_raw', schema='facebook')
    op.drop_index('idx_fb_mkt_listing_raw_event_listing', table_name='facebook_listings_new_raw', schema='facebook')
    op.drop_index('idx_fb_mkt_listing_raw_event_listed_at', table_name='facebook_listings_new_raw', schema='facebook')
    op.drop_index('idx_fb_mkt_listing_raw_current_listing', table_name='facebook_listings_new_raw', schema='facebook', postgresql_where=sa.text('valid_to IS NULL'))
    op.drop_table('facebook_listings_new_raw', schema='facebook')

    op.execute("DROP SCHEMA IF EXISTS stubhub")
