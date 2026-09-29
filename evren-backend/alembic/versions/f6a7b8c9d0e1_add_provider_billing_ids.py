"""add provider-agnostic billing ids (kept alongside legacy stripe ids)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-29

Adds `plans.provider_price_id` and `users.provider_customer_id` so the billing
layer can target any provider (Stripe, Dodo Payments, Paddle). The existing
`stripe_price_id` / `stripe_customer_id` columns are deliberately left in
place: the VS Code client reads `stripe_price_id` from `GET /plans`, so
renaming would break it. New writes go to the provider columns; reads fall
back to the legacy ones.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("provider_price_id", sa.String(length=100), nullable=True))
    op.add_column(
        "users", sa.Column("provider_customer_id", sa.String(length=100), nullable=True)
    )
    op.create_index(
        "ix_users_provider_customer_id", "users", ["provider_customer_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_users_provider_customer_id", table_name="users")
    op.drop_column("users", "provider_customer_id")
    op.drop_column("plans", "provider_price_id")