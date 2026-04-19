"""drop legacy posts.media_file_id column

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-19 22:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("posts", "media_file_id")


def downgrade() -> None:
    op.add_column("posts", sa.Column("media_file_id", sa.String(length=512), nullable=True))
