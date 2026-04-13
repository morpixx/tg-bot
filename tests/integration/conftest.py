"""
Integration test fixtures.

These tests require a running PostgreSQL instance. They are skipped automatically
when the database is not reachable.

Run with:
    pytest tests/integration/ -v --asyncio-mode=auto

Or set up DB via Docker:
    docker compose up -d postgres
    pytest tests/integration/ -v --asyncio-mode=auto
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Use a dedicated test database
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://bot:bot@localhost:5432/bot_test",
)


async def _db_available(url: str) -> bool:
    try:
        engine = create_async_engine(url, connect_args={"connect_timeout": 2})
        async with engine.connect():
            pass
        await engine.dispose()
        return True
    except Exception:
        return False


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires a running PostgreSQL")


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
async def db_engine():
    if not await _db_available(TEST_DB_URL):
        pytest.skip("PostgreSQL not reachable — skipping integration tests")

    engine = create_async_engine(TEST_DB_URL, echo=False)

    from db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def db_session(db_engine) -> AsyncSession:
    """Provide a transactional session, rolled back after each test."""
    async with db_engine.connect() as conn:
        await conn.begin()
        session_factory = async_sessionmaker(bind=conn, expire_on_commit=False)
        async with session_factory() as session:
            yield session
        await conn.rollback()


# ── Data factories ─────────────────────────────────────────────────────────────

@pytest.fixture
async def db_user(db_session):
    from db.models import User
    user = User(tg_id=100_000 + hash(uuid.uuid4()) % 1_000_000, username="testop", full_name="Test Operator")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def db_tg_session(db_session, db_user):
    from db.models import TelegramSession
    s = TelegramSession(
        user_id=db_user.tg_id,
        name="Test Session",
        encrypted_session="ENCRYPTEDVALUE",
        phone="+79001234567",
        has_premium=False,
        account_name="Test Account",
        account_username="testacc",
    )
    db_session.add(s)
    await db_session.flush()
    return s


@pytest.fixture
async def db_post(db_session, db_user):
    from db.models import Post, PostType
    p = Post(
        user_id=db_user.tg_id,
        title="Test Post",
        type=PostType.TEXT,
        text="Hello, World!",
    )
    db_session.add(p)
    await db_session.flush()
    return p


@pytest.fixture
async def db_chat(db_session, db_user):
    from db.models import TargetChat
    c = TargetChat(
        user_id=db_user.tg_id,
        chat_id=-1_001_234_567,
        title="Test Channel",
        username="testchannel",
        position=0,
    )
    db_session.add(c)
    await db_session.flush()
    return c


@pytest.fixture
async def db_campaign(db_session, db_user, db_post):
    from db.models import Campaign, CampaignSettings, CampaignStatus
    campaign = Campaign(
        user_id=db_user.tg_id,
        post_id=db_post.id,
        name="Test Campaign",
        status=CampaignStatus.DRAFT,
    )
    db_session.add(campaign)
    await db_session.flush()
    cfg = CampaignSettings(campaign_id=campaign.id)
    db_session.add(cfg)
    await db_session.flush()
    return campaign
