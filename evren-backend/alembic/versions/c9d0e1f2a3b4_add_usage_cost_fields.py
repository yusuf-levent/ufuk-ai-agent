"""add cost-accounting fields to usage_events + cost_daily_rollup

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-30

Margin tracking was blind: the gateway stripped the upstream's real USD cost
before answering the client (correct) but never persisted it (wrong). These
columns make "what did this user / model actually cost us" answerable:

* ``usage_events`` gains the real USD cost, the prompt-cache buckets, reasoning
  tokens, the concrete model that served the request (matters for ``auto`` and
  hidden sub-agent tiers), the parent request for sub-agent chains, the
  sticky-routing session id and the finish reason.
* ``cost_daily_rollup`` aggregates all of that per day x user x tier x model so
  margin queries stay fast as usage_events grows.

All new columns are additive and nullable/defaulted — no existing row changes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "usage_events",
        sa.Column("upstream_cost_usd", sa.Numeric(12, 6), nullable=True),
    )
    op.add_column(
        "usage_events",
        sa.Column(
            "cached_prompt_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column(
        "usage_events",
        sa.Column(
            "cache_write_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column(
        "usage_events",
        sa.Column(
            "reasoning_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column(
        "usage_events",
        sa.Column("selected_model_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "usage_events",
        sa.Column("parent_request_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_usage_events_parent_request_id", "usage_events", ["parent_request_id"]
    )
    op.add_column(
        "usage_events",
        sa.Column("session_id", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "usage_events",
        sa.Column("finish_reason", sa.String(length=32), nullable=True),
    )

    op.create_table(
        "cost_daily_rollup",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("tier_alias", sa.String(length=50), nullable=False),
        sa.Column("selected_model_id", sa.String(length=200), nullable=True),
        sa.Column("requests", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "completion_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "cached_prompt_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "cache_write_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "reasoning_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "credits_charged",
            sa.Numeric(14, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "upstream_cost_usd",
            sa.Numeric(14, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.UniqueConstraint(
            "day", "user_id", "tier_alias", "selected_model_id", name="uq_cost_rollup_key"
        ),
    )
    op.create_index("ix_cost_daily_rollup_day", "cost_daily_rollup", ["day"])
    op.create_index("ix_cost_daily_rollup_user_id", "cost_daily_rollup", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_cost_daily_rollup_user_id", table_name="cost_daily_rollup")
    op.drop_index("ix_cost_daily_rollup_day", table_name="cost_daily_rollup")
    op.drop_table("cost_daily_rollup")

    op.drop_column("usage_events", "finish_reason")
    op.drop_column("usage_events", "session_id")
    op.drop_index("ix_usage_events_parent_request_id", table_name="usage_events")
    op.drop_column("usage_events", "parent_request_id")
    op.drop_column("usage_events", "selected_model_id")
    op.drop_column("usage_events", "reasoning_tokens")
    op.drop_column("usage_events", "cache_write_tokens")
    op.drop_column("usage_events", "cached_prompt_tokens")
    op.drop_column("usage_events", "upstream_cost_usd")