"""Create pipeline audit tables: pipeline_runs and pipeline_errors.

Revision ID: a1b2c3d4e5f6
Revises: —
Create Date: 2026-07-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("source_file", sa.Text, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_records", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("success_count", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("error_count", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column(
            "error_breakdown",
            JSONB,
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "config",
            JSONB,
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "pipeline_errors",
        sa.Column(
            "id", sa.BigInteger, primary_key=True, autoincrement=True
        ),
        sa.Column("pipeline_run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("source_identifier", sa.Text, nullable=True),
        sa.Column("raw_data", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_run_id"],
            ["pipeline_runs.id"],
            name="fk_pipeline_errors_run_id",
        ),
    )

    op.create_index(
        "idx_pipeline_errors_run_id",
        "pipeline_errors",
        ["pipeline_run_id"],
    )
    op.create_index(
        "idx_pipeline_errors_error_code",
        "pipeline_errors",
        ["error_code"],
    )


def downgrade() -> None:
    op.drop_table("pipeline_errors")
    op.drop_table("pipeline_runs")
