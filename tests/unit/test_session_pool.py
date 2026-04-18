from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worker.session_pool import SessionPool


@pytest.fixture
def pool() -> SessionPool:
    return SessionPool()


@pytest.fixture
def fake_session() -> MagicMock:
    s = MagicMock()
    s.id = uuid.uuid4()
    s.name = "Test Session"
    s.encrypted_session = "ENCRYPTED"
    return s


# ── Initialization ────────────────────────────────────────────────────────────

def test_pool_starts_empty(pool) -> None:
    assert pool._clients == {}


async def test_disconnect_all_empty(pool) -> None:
    await pool.disconnect_all()  # should not raise


# ── get_or_connect ─────────────────────────────────────────────────────────────

async def test_decrypt_failure_returns_none(pool, fake_session) -> None:
    with patch("worker.session_pool.decrypt", side_effect=Exception("bad key")):
        result = await pool.get_or_connect(fake_session)
    assert result is None


async def test_not_authorized_returns_none(pool, fake_session) -> None:
    mock_client = AsyncMock()
    mock_client.is_connected.return_value = False
    mock_client.is_user_authorized.return_value = False

    with (
        patch("worker.session_pool.decrypt", return_value="plain"),
        patch("worker.session_pool.StringSession", return_value=MagicMock()),
        patch("worker.session_pool.TelegramClient", return_value=mock_client),
    ):
        result = await pool.get_or_connect(fake_session)

    assert result is None
    mock_client.disconnect.assert_called_once()


async def test_authorized_client_added_to_pool(pool, fake_session) -> None:
    mock_client = AsyncMock()
    mock_client.is_connected.return_value = False
    mock_client.is_user_authorized.return_value = True

    with (
        patch("worker.session_pool.decrypt", return_value="plain"),
        patch("worker.session_pool.StringSession", return_value=MagicMock()),
        patch("worker.session_pool.TelegramClient", return_value=mock_client),
    ):
        result = await pool.get_or_connect(fake_session)

    assert result is mock_client
    assert fake_session.id in pool._clients


async def test_already_connected_returns_cached(pool, fake_session) -> None:
    mock_client = AsyncMock()
    mock_client.is_connected.return_value = True
    pool._clients[fake_session.id] = mock_client

    result = await pool.get_or_connect(fake_session)
    assert result is mock_client


async def test_general_exception_returns_none(pool, fake_session) -> None:
    with (
        patch("worker.session_pool.decrypt", return_value="plain"),
        patch("worker.session_pool.StringSession", return_value=MagicMock()),
        patch("worker.session_pool.TelegramClient", side_effect=RuntimeError("oops")),
    ):
        result = await pool.get_or_connect(fake_session)
    assert result is None


# ── disconnect ────────────────────────────────────────────────────────────────

async def test_disconnect_removes_client(pool, fake_session) -> None:
    mock_client = AsyncMock()
    pool._clients[fake_session.id] = mock_client
    await pool.disconnect(fake_session.id)
    assert fake_session.id not in pool._clients
    mock_client.disconnect.assert_called_once()


async def test_disconnect_nonexistent_id(pool) -> None:
    await pool.disconnect(uuid.uuid4())  # should not raise


async def test_disconnect_all(pool) -> None:
    c1, c2 = AsyncMock(), AsyncMock()
    id1, id2 = uuid.uuid4(), uuid.uuid4()
    pool._clients[id1] = c1
    pool._clients[id2] = c2

    await pool.disconnect_all()

    assert pool._clients == {}
    c1.disconnect.assert_called_once()
    c2.disconnect.assert_called_once()


# ── health_check ──────────────────────────────────────────────────────────────

async def test_health_check_alive(pool, fake_session) -> None:
    mock_client = AsyncMock()
    mock_client.is_connected.return_value = True
    mock_client.is_user_authorized.return_value = True
    mock_client.get_me = AsyncMock(return_value=MagicMock())

    with (
        patch("worker.session_pool.decrypt", return_value="plain"),
        patch("worker.session_pool.StringSession", return_value=MagicMock()),
        patch("worker.session_pool.TelegramClient", return_value=mock_client),
    ):
        alive = await pool.health_check(fake_session)

    assert alive is True


async def test_health_check_dead(pool, fake_session) -> None:
    with patch.object(pool, "get_or_connect", return_value=None):
        alive = await pool.health_check(fake_session)
    assert alive is False


async def test_health_check_get_me_fails(pool, fake_session) -> None:
    mock_client = AsyncMock()
    mock_client.get_me = AsyncMock(side_effect=Exception("disconnected"))

    with patch.object(pool, "get_or_connect", return_value=mock_client):
        alive = await pool.health_check(fake_session)

    assert alive is False
    assert fake_session.id not in pool._clients
