"""store manual post media as bytes instead of bot-api file_id

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-19 21:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("media_bytes", sa.LargeBinary(), nullable=True))
    op.add_column("posts", sa.Column("media_filename", sa.String(length=256), nullable=True))


def downgrade() -> None:
    op.drop_column("posts", "media_filename")
    op.drop_column("posts", "media_bytes")
