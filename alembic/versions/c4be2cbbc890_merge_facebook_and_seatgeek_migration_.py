"""merge facebook and seatgeek migration branches

Revision ID: c4be2cbbc890
Revises: c1d2e3f4a5b6, e6a689df000c
Create Date: 2026-09-17 23:13:21.553677

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c4be2cbbc890'
down_revision: Union[str, None] = ('c1d2e3f4a5b6', 'e6a689df000c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
