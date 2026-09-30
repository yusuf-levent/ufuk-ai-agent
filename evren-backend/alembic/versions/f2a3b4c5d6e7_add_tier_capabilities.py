"""add model capability metadata to model_tiers

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-09-30

The picker and the billing unit both need to know WHAT a tier can do:

* ``output_modalities`` — what the model produces (["text"] vs
  ["text","image"]). Reading images (vision) is NOT the same as generating
  them; without this column the gateway cannot route image-generation work or
  keep text-only tiers out of it.
* ``supports_tools`` — user-facing tiers must honour tool calling (agent
  workflows depend on it). Image-generation models mostly do not, so they can
  only sit behind a server-side tool facade.
* ``pricing_unit`` — token | image | request. Only TOKEN tiers use the
  credit-per-1k formula; billing a generated image as tokens would be wrong.
* ``max_images_per_request`` — per-request generation ceiling (IMAGE tiers).
* ``is_internal`` — hidden sub-agent / server-side tiers. Invisible AND
  unusable from the public gateway: a user request naming one is rejected, so
  nobody can sidestep the curated picker to reach a hidden (often pricier)
  model.

All columns are defaulted so existing rows keep working unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_tiers",
        sa.Column(
            "output_modalities",
            sa.ARRAY(sa.String(length=20)),
            nullable=False,
            server_default=sa.text("'{text}'"),
        ),
    )
    op.add_column(
        "model_tiers",
        sa.Column(
            "supports_tools", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
    )
    op.add_column(
        "model_tiers",
        sa.Column(
            "pricing_unit", sa.String(length=32), nullable=False, server_default=sa.text("'token'")
        ),
    )
    op.add_column(
        "model_tiers",
        sa.Column("max_images_per_request", sa.Integer(), nullable=True),
    )
    op.add_column(
        "model_tiers",
        sa.Column(
            "is_internal", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )


def downgrade() -> None:
    op.drop_column("model_tiers", "is_internal")
    op.drop_column("model_tiers", "max_images_per_request")
    op.drop_column("model_tiers", "pricing_unit")
    op.drop_column("model_tiers", "supports_tools")
    op.drop_column("model_tiers", "output_modalities")