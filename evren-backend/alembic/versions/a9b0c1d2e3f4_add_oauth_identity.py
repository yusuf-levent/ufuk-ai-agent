"""Add federated identity columns for Google / Apple sign-in.

Revision ID: a9b0c1d2e3f4
Revises: d7e8f9a0b1c2
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9b0c1d2e3f4"
down_revision: str | Sequence[str] | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("auth_provider", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("provider_subject", sa.String(255), nullable=True))
    # A provider identity maps to exactly one account. Postgres treats NULLs as
    # distinct, so email/password rows (both columns NULL) are unaffected.
    op.create_unique_constraint(
        "uq_users_auth_provider_subject", "users", ["auth_provider", "provider_subject"]
    )
    # Federated accounts have no password.
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=True)


def downgrade() -> None:
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=False)
    op.drop_constraint("uq_users_auth_provider_subject", "users", type_="unique")
    op.drop_column("users", "provider_subject")
    op.drop_column("users", "auth_provider")