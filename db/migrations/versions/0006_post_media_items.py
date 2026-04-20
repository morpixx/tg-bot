"""add post_media_items for album posts

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-20 18:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "post_media_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "post_id",
            UUID(as_uuid=True),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("media_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("media_filename", sa.String(length=256), nullable=True),
    )
    op.create_index(
        "ix_post_media_items_post_id", "post_media_items", ["post_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_post_media_items_post_id", table_name="post_media_items")
    op.drop_table("post_media_items")
