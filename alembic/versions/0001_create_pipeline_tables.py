"""Create pipeline_runs table.

Revision ID: a1b2c3d4e5f6
Revises: —
Create Date: 2026-07-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("source", sa.Text, nullable=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_records", sa.BigInteger, nullable=True),
        sa.Column("success_count", sa.BigInteger, nullable=True),
        sa.Column("error_count", sa.BigInteger, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index("idx_pipeline_runs_lstarted_at", "pipeline_runs", ["started_at"])
    op.create_index("idx_pipeline_runs_created_at", "pipeline_runs", ["created_at"])


def downgrade() -> None:
    op.drop_table("pipeline_runs")
