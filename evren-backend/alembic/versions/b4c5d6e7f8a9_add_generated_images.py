"""add generated_images table + plan image quota

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-09-30

Image generation gets its own storage and quota:

* ``generated_images`` — metadata for every generated image (prompt, quality,
  dimensions, storage path, credits charged, real USD cost). Binary data lives
  on disk/object storage; this table tracks what matters for quota enforcement,
  cost attribution, and the user's gallery. The upstream model id stays internal
  (like hidden sub-agent tiers).
* ``plans.monthly_image_quota`` — monthly image COUNT (not credits). Separate
  from the credit budget because image pricing units vary (image / megapixel /
  token) and a count is what users understand. NULL = no image generation.

Quality tiers map to OpenRouter's `variant` pricing (1K/2K/4K) and drive a
credit multiplier: standard=1x, high=2x, ultra=4x. This keeps the user's mental
model simple ("1 image = N credits") while the multiplier tracks the real
megapixel-based cost difference.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: str | Sequence[str] | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "generated_images",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("upstream_model_id", sa.String(length=200), nullable=False),
        sa.Column("prompt", sa.String(length=2000), nullable=False),
        sa.Column("quality", sa.String(length=32), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("format", sa.String(length=10), nullable=False, server_default=sa.text("'png'")),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column(
            "credits_charged", sa.Numeric(12, 6), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("upstream_cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_generated_images_user_id", "generated_images", ["user_id"])
    op.create_index("ix_generated_images_created_at", "generated_images", ["created_at"])

    op.add_column(
        "plans", sa.Column("monthly_image_quota", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("plans", "monthly_image_quota")
    op.drop_index("ix_generated_images_created_at", table_name="generated_images")
    op.drop_index("ix_generated_images_user_id", table_name="generated_images")
    op.drop_table("generated_images")