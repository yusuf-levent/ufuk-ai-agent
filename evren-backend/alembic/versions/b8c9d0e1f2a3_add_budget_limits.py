"""add per-request and rolling-window credit budgets to plans

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-09-30

Two ceilings that together act as the sub-agent cost kill-switch:

* ``max_credits_per_request`` — a single LLM call can never reserve more than
  this, so one runaway prompt cannot drain the period in one shot.
* ``max_credits_per_window`` over ``budget_window_seconds`` — total credits
  burned in a short burst can never exceed this. A nested sub-agent chain
  fires many calls in a burst; each is individually small, so only a window
  budget stops the exponential blow-up.

Both are nullable: NULL means unlimited (historical behaviour).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "plans",
        sa.Column("max_credits_per_request", sa.Numeric(12, 6), nullable=True),
    )
    op.add_column(
        "plans",
        sa.Column("max_credits_per_window", sa.Numeric(12, 6), nullable=True),
    )
    op.add_column(
        "plans",
        sa.Column(
            "budget_window_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("300"),
        ),
    )


def downgrade() -> None:
    op.drop_column("plans", "budget_window_seconds")
    op.drop_column("plans", "max_credits_per_window")
    op.drop_column("plans", "max_credits_per_request")