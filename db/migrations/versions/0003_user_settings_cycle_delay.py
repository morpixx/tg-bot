"""add cycle delay randomization to user_settings

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-15 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_settings", sa.Column("cycle_delay_randomize", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("user_settings", sa.Column("cycle_delay_min", sa.Integer(), nullable=False, server_default="30"))
    op.add_column("user_settings", sa.Column("cycle_delay_max", sa.Integer(), nullable=False, server_default="120"))


def downgrade() -> None:
    op.drop_column("user_settings", "cycle_delay_max")
    op.drop_column("user_settings", "cycle_delay_min")
    op.drop_column("user_settings", "cycle_delay_randomize")
