"""add tooltip metadata to model_tiers

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-09-30

Tooltip fields for the model picker's ℹ️ hover card. Curated manually via
seed/admin — never derived from upstream pricing. Levels are 1-5 scales
(cost: 1=very cheap … 5=very expensive; speed: 1=slow … 5=fast; quality:
1=basic … 5=exceptional).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: str | Sequence[str] | None = "b4c5d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_tiers", sa.Column("tooltip_title", sa.String(length=100), nullable=True))
    op.add_column("model_tiers", sa.Column("tooltip_body", sa.String(length=500), nullable=True))
    op.add_column("model_tiers", sa.Column("tooltip_cost_level", sa.Integer(), nullable=True))
    op.add_column("model_tiers", sa.Column("tooltip_speed_level", sa.Integer(), nullable=True))
    op.add_column("model_tiers", sa.Column("tooltip_quality_level", sa.Integer(), nullable=True))
    op.add_column("model_tiers", sa.Column("tooltip_best_for", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("model_tiers", "tooltip_best_for")
    op.drop_column("model_tiers", "tooltip_quality_level")
    op.drop_column("model_tiers", "tooltip_speed_level")
    op.drop_column("model_tiers", "tooltip_cost_level")
    op.drop_column("model_tiers", "tooltip_body")
    op.drop_column("model_tiers", "tooltip_title")