"""add input_modalities to model_tiers

Revision ID: d7e8f9a0b1c2
Revises: d6e7f8a9b0c1
Create Date: 2026-10-01

``output_modalities`` describes what a model PRODUCES; vision support is about
what it can READ. Without a separate ``input_modalities`` column the picker
cannot tell "reads images" (vision) from "draws images" (generation), and the
seed was forced to mislabel chat tiers as image generators. This column makes
the distinction explicit: user-facing chat tiers carry
``input_modalities = ['text','image']`` (vision) and
``output_modalities = ['text']``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: str | Sequence[str] | None = "d6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_tiers",
        sa.Column(
            "input_modalities",
            sa.ARRAY(sa.String(length=20)),
            nullable=False,
            server_default=sa.text("'{text}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("model_tiers", "input_modalities")