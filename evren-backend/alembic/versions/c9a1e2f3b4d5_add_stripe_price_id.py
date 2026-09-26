"""add stripe_price_id to plans

Revision ID: c9a1e2f3b4d5
Revises: b4ba0fdb01f2
Create Date: 2026-09-26

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9a1e2f3b4d5"
down_revision: str | None = "b4ba0fdb01f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("stripe_price_id", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("plans", "stripe_price_id")
