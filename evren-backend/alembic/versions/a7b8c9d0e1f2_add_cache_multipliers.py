"""add prompt-cache pricing multipliers to model_tiers

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-30

Cached prompt tokens are billed at a discounted input rate and cache writes at
a premium one (provider dependent: DeepSeek/Alibaba/Anthropic read 0.1x,
Google/Moonshot 0.25x, Groq 0.5x; Anthropic/Alibaba write 1.25x). Both columns
default to 1.0 so existing tiers keep their historical billing behaviour until
an operator sets the real multipliers.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_tiers",
        sa.Column(
            "cache_read_multiplier",
            sa.Numeric(6, 4),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
    )
    op.add_column(
        "model_tiers",
        sa.Column(
            "cache_write_multiplier",
            sa.Numeric(6, 4),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("model_tiers", "cache_write_multiplier")
    op.drop_column("model_tiers", "cache_read_multiplier")