from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ── Enums ─────────────────────────────────────────────────────────────────────

class PostType(str, enum.Enum):
    FORWARDED = "forwarded"
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    MEDIA_GROUP = "media_group"


class CampaignStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"


class BroadcastStatus(str, enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"
    FLOOD_WAIT = "flood_wait"
    SKIPPED = "skipped"


# SQLAlchemy native PostgreSQL enums use .name (uppercase) by default.
# Use values_callable so the stored value matches the migration (lowercase).
def _enum_values(obj: type[enum.Enum]) -> list[str]:
    return [e.value for e in obj]


# ── Models ────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str | None] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sessions: Mapped[list[TelegramSession]] = relationship(back_populates="user", cascade="all, delete-orphan")
    posts: Mapped[list[Post]] = relationship(back_populates="user", cascade="all, delete-orphan")
    target_chats: Mapped[list[TargetChat]] = relationship(back_populates="user", cascade="all, delete-orphan")
    campaigns: Mapped[list[Campaign]] = relationship(back_populates="user", cascade="all, delete-orphan")
    global_settings: Mapped[UserSettings | None] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")


class TelegramSession(Base):
    __tablename__ = "telegram_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(32))
    # Fernet-encrypted Telethon StringSession
    encrypted_session: Mapped[str] = mapped_column(Text)
    has_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    account_name: Mapped[str | None] = mapped_column(String(256))  # TG display name
    account_username: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="sessions")
    campaign_sessions: Mapped[list[CampaignSession]] = relationship(back_populates="session", cascade="all, delete-orphan")
    broadcast_logs: Mapped[list[BroadcastLog]] = relationship(back_populates="session", cascade="all, delete-orphan")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(256))
    type: Mapped[PostType] = mapped_column(Enum(PostType, values_callable=_enum_values))

    # For forwarded posts
    source_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    source_message_id: Mapped[int | None] = mapped_column(Integer)

    # For manual posts
    text: Mapped[str | None] = mapped_column(Text)
    # Serialized JSON list of entities (for Premium emoji support)
    text_entities: Mapped[str | None] = mapped_column(Text)
    media_file_id: Mapped[str | None] = mapped_column(String(512))
    media_type: Mapped[str | None] = mapped_column(String(32))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="posts")
    campaigns: Mapped[list[Campaign]] = relationship(back_populates="post")


class TargetChat(Base):
    __tablename__ = "target_chats"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(256))
    username: Mapped[str | None] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("user_id", "chat_id", name="uq_user_chat"),)

    user: Mapped[User] = relationship(back_populates="target_chats")
    campaign_chats: Mapped[list[CampaignChat]] = relationship(back_populates="chat", cascade="all, delete-orphan")


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"))
    post_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("posts.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(256))
    status: Mapped[CampaignStatus] = mapped_column(Enum(CampaignStatus, values_callable=_enum_values), default=CampaignStatus.DRAFT)
    current_cycle: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="campaigns")
    post: Mapped[Post] = relationship(back_populates="campaigns")
    settings: Mapped[CampaignSettings] = relationship(back_populates="campaign", uselist=False, cascade="all, delete-orphan")
    campaign_sessions: Mapped[list[CampaignSession]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    campaign_chats: Mapped[list[CampaignChat]] = relationship(back_populates="campaign", cascade="all, delete-orphan", order_by="CampaignChat.position")
    broadcast_logs: Mapped[list[BroadcastLog]] = relationship(back_populates="campaign", cascade="all, delete-orphan")


class CampaignSettings(Base):
    __tablename__ = "campaign_settings"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True
    )
    # Delay between chats
    delay_between_chats: Mapped[int] = mapped_column(Integer, default=5)
    randomize_delay: Mapped[bool] = mapped_column(Boolean, default=False)
    randomize_min: Mapped[int] = mapped_column(Integer, default=3)
    randomize_max: Mapped[int] = mapped_column(Integer, default=10)
    # After each full cycle
    shuffle_after_cycle: Mapped[bool] = mapped_column(Boolean, default=False)
    delay_between_cycles: Mapped[int] = mapped_column(Integer, default=60)
    cycle_delay_randomize: Mapped[bool] = mapped_column(Boolean, default=False)
    cycle_delay_min: Mapped[int] = mapped_column(Integer, default=30)
    cycle_delay_max: Mapped[int] = mapped_column(Integer, default=120)
    # How many cycles (None = infinite)
    max_cycles: Mapped[int | None] = mapped_column(Integer)
    # forward_messages vs copy (send_message)
    forward_mode: Mapped[bool] = mapped_column(Boolean, default=True)

    campaign: Mapped[Campaign] = relationship(back_populates="settings")


class CampaignSession(Base):
    """Links a session to a campaign with its timing offset."""
    __tablename__ = "campaign_sessions"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telegram_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    # Seconds after campaign start when this session begins broadcasting
    delay_offset_seconds: Mapped[int] = mapped_column(Integer, default=0)

    campaign: Mapped[Campaign] = relationship(back_populates="campaign_sessions")
    session: Mapped[TelegramSession] = relationship(back_populates="campaign_sessions")


class CampaignChat(Base):
    """Ordered list of chats for a campaign."""
    __tablename__ = "campaign_chats"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("target_chats.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)

    campaign: Mapped[Campaign] = relationship(back_populates="campaign_chats")
    chat: Mapped[TargetChat] = relationship(back_populates="campaign_chats")


class BroadcastLog(Base):
    __tablename__ = "broadcast_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE")
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telegram_sessions.id", ondelete="CASCADE")
    )
    chat_id: Mapped[int] = mapped_column(BigInteger)
    cycle: Mapped[int] = mapped_column(Integer, default=1)
    message_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[BroadcastStatus] = mapped_column(Enum(BroadcastStatus, values_callable=_enum_values))
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    campaign: Mapped[Campaign] = relationship(back_populates="broadcast_logs")
    session: Mapped[TelegramSession] = relationship(back_populates="broadcast_logs")


class UserSettings(Base):
    """Global default campaign settings per user."""
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), primary_key=True)
    delay_between_chats: Mapped[int] = mapped_column(Integer, default=5)
    randomize_delay: Mapped[bool] = mapped_column(Boolean, default=False)
    randomize_min: Mapped[int] = mapped_column(Integer, default=3)
    randomize_max: Mapped[int] = mapped_column(Integer, default=10)
    shuffle_after_cycle: Mapped[bool] = mapped_column(Boolean, default=False)
    delay_between_cycles: Mapped[int] = mapped_column(Integer, default=60)
    cycle_delay_randomize: Mapped[bool] = mapped_column(Boolean, default=False)
    cycle_delay_min: Mapped[int] = mapped_column(Integer, default=30)
    cycle_delay_max: Mapped[int] = mapped_column(Integer, default=120)
    max_cycles: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forward_mode: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(back_populates="global_settings")
