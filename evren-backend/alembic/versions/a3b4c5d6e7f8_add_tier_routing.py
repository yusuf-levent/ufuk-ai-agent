"""add fallback chain + router plugin to model_tiers

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-09-30

Two routing features, both driven entirely by server-side tier config (a
client must never name an upstream model — see UpstreamClient.SERVER_ONLY_FIELDS):

* ``fallback_model_ids`` — ordered upstream model ids tried when the primary
  fails (rate limit, outage, refusal). Sent as an OpenRouter ``models`` array.
  Entries must be same-or-cheaper than the primary: a pricier fallback would
  let a transient error silently inflate the user's bill.
* ``routing_plugin`` — optional OpenRouter router plugin ("auto-router" |
  "pareto-router"). The gateway pins ``allowed_models`` to the tier's own chain
  and ``costTier`` to "low", so the router can never pick an off-list or
  expensive model.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_tiers",
        sa.Column(
            "fallback_model_ids",
            sa.ARRAY(sa.String(length=200)),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "model_tiers",
        sa.Column("routing_plugin", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_tiers", "routing_plugin")
    op.drop_column("model_tiers", "fallback_model_ids")