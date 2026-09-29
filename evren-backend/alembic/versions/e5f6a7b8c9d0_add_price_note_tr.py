"""add price_note_tr to model_tiers

Revision ID: e5f6a7b8c9d0
Revises: d5e6f7a8b9c0
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_tiers", sa.Column("price_note_tr", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("model_tiers", "price_note_tr")