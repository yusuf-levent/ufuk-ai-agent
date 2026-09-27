"""add price_note/speed_hint/quality_hint to model_tiers

Revision ID: a1b2c3d4e5f6
Revises: c9a1e2f3b4d5
Create Date: 2026-09-27

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "c9a1e2f3b4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_tiers", sa.Column("price_note", sa.String(length=200), nullable=True))
    op.add_column("model_tiers", sa.Column("speed_hint", sa.Integer(), nullable=True))
    op.add_column("model_tiers", sa.Column("quality_hint", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("model_tiers", "quality_hint")
    op.drop_column("model_tiers", "speed_hint")
    op.drop_column("model_tiers", "price_note")
