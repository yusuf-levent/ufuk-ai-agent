"""add price_usd to plans and stripe_customer_id to users

Revision ID: d5e6f7a8b9c0
Revises: a1b2c3d4e5f6
Create Date: 2026-09-28

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("price_usd", sa.Numeric(10, 2), nullable=True))
    op.add_column("users", sa.Column("stripe_customer_id", sa.String(length=100), nullable=True))
    op.create_index("ix_users_stripe_customer_id", "users", ["stripe_customer_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_stripe_customer_id", table_name="users")
    op.drop_column("users", "stripe_customer_id")
    op.drop_column("plans", "price_usd")