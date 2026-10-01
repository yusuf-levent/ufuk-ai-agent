"""add billing event idempotency + image quota period key

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-10-01

Two financial-safety columns:

* ``subscriptions.billing_event_id`` — provider webhook event id that granted
  or renewed this subscription. Unique when present, so a redelivered webhook
  can never grant a second period (double-grant protection). NULL for
  grandfathered/admin-assigned rows.
* ``generated_images.period_key`` — the billing period an image was charged
  against. The image quota must reset with the *billing period*, not the
  calendar month: a user who subscribes mid-month would otherwise get two
  quotas in one paid period. NULL rows fall back to the calendar-month window
  (legacy behaviour) and are invisible to the new period-scoped counter.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: str | Sequence[str] | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subscriptions", sa.Column("billing_event_id", sa.String(length=120), nullable=True)
    )
    op.create_unique_constraint(
        "uq_subscriptions_billing_event_id", "subscriptions", ["billing_event_id"]
    )
    op.add_column(
        "generated_images", sa.Column("period_key", sa.String(length=20), nullable=True)
    )
    op.create_index("ix_generated_images_period_key", "generated_images", ["period_key"])


def downgrade() -> None:
    op.drop_index("ix_generated_images_period_key", table_name="generated_images")
    op.drop_column("generated_images", "period_key")
    op.drop_constraint("uq_subscriptions_billing_event_id", "subscriptions", type_="unique")
    op.drop_column("subscriptions", "billing_event_id")