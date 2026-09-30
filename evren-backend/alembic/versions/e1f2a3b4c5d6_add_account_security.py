"""add account-sharing deterrents (terms acceptance + concurrency + soft flag)

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-09-30

Three layers that discourage shared accounts without punishing honest users:

* ``users.terms_accepted_at`` / ``terms_version`` — the contractual clause
  ("you may not share your account"), recorded at signup. Nullable so accounts
  created before the clause existed stay grandfathered in; retroactively
  locking out paying users would be unfair and legally shaky.
* ``plans.max_concurrent_requests`` — hard cap on in-flight LLM requests per
  account. Bounds blast radius when an account IS shared and keeps one account
  from monopolising the shared upstream key. NULL = unlimited.
* ``users.security_flagged`` / ``security_flag_reason`` — SOFT abuse flag set
  when usage looks like a shared account (bursts, many parallel sessions).
  Never auto-bans: a human reviews.

No IP addresses or device fingerprints are stored — see docs/privacy-rules.md.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("terms_version", sa.String(length=20), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "security_flagged", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "users", sa.Column("security_flag_reason", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "plans", sa.Column("max_concurrent_requests", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("plans", "max_concurrent_requests")
    op.drop_column("users", "security_flag_reason")
    op.drop_column("users", "security_flagged")
    op.drop_column("users", "terms_version")
    op.drop_column("users", "terms_accepted_at")