"""add reasoning_multiplier to model_tiers

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-09-30

Reasoning (chain-of-thought) tokens are already counted inside
``completion_tokens`` by every upstream we use, so they are already billed at
the plain output rate. This multiplier is a *relative weight on that subset*,
not an extra charge on top of it — the billing formula subtracts the reasoning
portion from the plain-output term before applying the multiplier, so a value
of 1.0 reproduces today's cost exactly (no double billing).

Defaults to 1.0 so existing tiers keep their historical billing behaviour
until an operator opts into a reasoning premium.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | Sequence[str] | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_tiers",
        sa.Column(
            "reasoning_multiplier",
            sa.Numeric(6, 4),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("model_tiers", "reasoning_multiplier")