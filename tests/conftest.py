from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

# ── Env vars must be set before any project imports ───────────────────────────
os.environ.setdefault("BOT_TOKEN", "1234567890:AABBccDDeeFF")
os.environ.setdefault("OWNER_ID", "123456789")
os.environ.setdefault("TELETHON_API_ID", "12345678")
os.environ.setdefault("TELETHON_API_HASH", "abcdef1234567890abcdef1234567890")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://bot:bot@localhost/bot_test")
os.environ.setdefault("DATABASE_SYNC_URL", "postgresql+psycopg2://bot:bot@localhost/bot_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())


# ── Shared model factories (no DB required) ───────────────────────────────────

@pytest.fixture
def user_id() -> int:
    return 123456789


@pytest.fixture
def session_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def campaign_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def post_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def mock_bot() -> AsyncMock:
    bot = AsyncMock()
    bot.get_chat_member = AsyncMock()
    bot.get_chat = AsyncMock()
    bot.create_chat_invite_link = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


@pytest.fixture
def mock_db_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.delete = AsyncMock()
    session.execute = AsyncMock()
    session.get = AsyncMock()
    return session


@pytest.fixture
def make_user():
    def _make(tg_id: int = 111, username: str = "testuser", active: bool = True):
        from db.models import User
        u = User(tg_id=tg_id, username=username, full_name="Test User", is_active=active)
        return u
    return _make


@pytest.fixture
def make_tg_session(session_id):
    def _make(user_id: int = 111, has_premium: bool = False, is_active: bool = True):
        from db.models import TelegramSession
        s = TelegramSession(
            id=session_id,
            user_id=user_id,
            name="Test Session",
            encrypted_session="ENCRYPTED",
            has_premium=has_premium,
            is_active=is_active,
            account_name="Test Account",
            account_username="testaccount",
        )
        return s
    return _make


@pytest.fixture
def make_post(post_id):
    def _make(user_id: int = 111, post_type: str = "text"):
        from db.models import Post, PostType
        p = Post(
            id=post_id,
            user_id=user_id,
            title="Test Post",
            type=PostType(post_type),
            text="Hello World",
        )
        return p
    return _make


@pytest.fixture
def make_campaign(campaign_id, post_id):
    def _make(user_id: int = 111, status: str = "active"):
        from db.models import Campaign, CampaignSettings, CampaignStatus
        c = Campaign(
            id=campaign_id,
            user_id=user_id,
            post_id=post_id,
            name="Test Campaign",
            status=CampaignStatus(status),
            current_cycle=0,
        )
        cfg = CampaignSettings(
            campaign_id=campaign_id,
            delay_between_chats=1,
            randomize_delay=False,
            shuffle_after_cycle=False,
            delay_between_cycles=1,
            forward_mode=True,
        )
        c.settings = cfg
        c.campaign_sessions = []
        c.campaign_chats = []
        return c
    return _make
