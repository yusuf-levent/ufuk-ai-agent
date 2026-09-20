from __future__ import annotations

from alembic import command
from tests.conftest import alembic_config


def test_migrate_down_and_up() -> None:
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
