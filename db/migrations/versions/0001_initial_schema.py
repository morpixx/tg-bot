"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-13 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("full_name", sa.String(length=256), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("tg_id"),
    )

    op.create_table(
        "telegram_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("encrypted_session", sa.Text(), nullable=False),
        sa.Column("has_premium", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("account_name", sa.String(length=256), nullable=True),
        sa.Column("account_username", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_used", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.tg_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("type", sa.Enum("forwarded", "text", "photo", "video", "document", "media_group", name="posttype"), nullable=False),
        sa.Column("source_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("source_message_id", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("text_entities", sa.Text(), nullable=True),
        sa.Column("media_file_id", sa.String(length=512), nullable=True),
        sa.Column("media_type", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.tg_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "target_chats",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["user_id"], ["users.tg_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "chat_id", name="uq_user_chat"),
    )

    op.create_table(
        "campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("status", sa.Enum("draft", "active", "paused", "stopped", "completed", name="campaignstatus"), nullable=False, server_default="draft"),
        sa.Column("current_cycle", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.tg_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "campaign_settings",
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delay_between_chats", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("randomize_delay", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("randomize_min", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("randomize_max", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("shuffle_after_cycle", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("delay_between_cycles", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("cycle_delay_randomize", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("cycle_delay_min", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("cycle_delay_max", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("max_cycles", sa.Integer(), nullable=True),
        sa.Column("forward_mode", sa.Boolean(), nullable=False, server_default="true"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("campaign_id"),
    )

    op.create_table(
        "campaign_sessions",
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delay_offset_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["telegram_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("campaign_id", "session_id"),
    )

    op.create_table(
        "campaign_chats",
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chat_id"], ["target_chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("campaign_id", "chat_id"),
    )

    op.create_table(
        "broadcast_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("cycle", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.Enum("success", "failed", "flood_wait", "skipped", name="broadcaststatus"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["telegram_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Indexes
    op.create_index("ix_broadcast_logs_campaign_id", "broadcast_logs", ["campaign_id"])
    op.create_index("ix_campaigns_user_id_status", "campaigns", ["user_id", "status"])
    op.create_index("ix_telegram_sessions_user_id", "telegram_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_table("broadcast_logs")
    op.drop_table("campaign_chats")
    op.drop_table("campaign_sessions")
    op.drop_table("campaign_settings")
    op.drop_table("campaigns")
    op.drop_table("target_chats")
    op.drop_table("posts")
    op.drop_table("telegram_sessions")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS posttype")
    op.execute("DROP TYPE IF EXISTS campaignstatus")
    op.execute("DROP TYPE IF EXISTS broadcaststatus")
