"""add user_settings table

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-14 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("delay_between_chats", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("randomize_delay", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("randomize_min", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("randomize_max", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("shuffle_after_cycle", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("delay_between_cycles", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("max_cycles", sa.Integer(), nullable=True),
        sa.Column("forward_mode", sa.Boolean(), nullable=False, server_default="true"),
        sa.ForeignKeyConstraint(["user_id"], ["users.tg_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_settings")
