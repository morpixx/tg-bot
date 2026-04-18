from __future__ import annotations

import pytest

from db.repositories.chat_repo import ChatRepository

pytestmark = pytest.mark.integration


async def test_create_chat(db_session, db_user) -> None:
    repo = ChatRepository(db_session)
    chat = await repo.create(db_user.tg_id, -1001, "Test Channel", "testchannel")
    assert chat.id is not None
    assert chat.chat_id == -1001
    assert chat.title == "Test Channel"
    assert chat.username == "testchannel"
    assert chat.position == 0


async def test_position_increments(db_session, db_user) -> None:
    repo = ChatRepository(db_session)
    c1 = await repo.create(db_user.tg_id, -2001, "Chat 1")
    c2 = await repo.create(db_user.tg_id, -2002, "Chat 2")
    c3 = await repo.create(db_user.tg_id, -2003, "Chat 3")
    assert c1.position == 0
    assert c2.position == 1
    assert c3.position == 2


async def test_get_by_user_ordered(db_session, db_user) -> None:
    repo = ChatRepository(db_session)
    await repo.create(db_user.tg_id, -3001, "A")
    await repo.create(db_user.tg_id, -3002, "B")
    chats = await repo.get_by_user(db_user.tg_id)
    positions = [c.position for c in chats]
    assert positions == sorted(positions)


async def test_find_by_chat_id(db_session, db_user, db_chat) -> None:
    repo = ChatRepository(db_session)
    found = await repo.find_by_chat_id(db_user.tg_id, db_chat.chat_id)
    assert found is not None
    assert found.id == db_chat.id


async def test_find_by_chat_id_missing(db_session, db_user) -> None:
    repo = ChatRepository(db_session)
    assert await repo.find_by_chat_id(db_user.tg_id, -999) is None


async def test_get_chat(db_session, db_chat) -> None:
    repo = ChatRepository(db_session)
    found = await repo.get(db_chat.id)
    assert found is not None
    assert found.id == db_chat.id


async def test_delete_chat(db_session, db_chat) -> None:
    repo = ChatRepository(db_session)
    await repo.delete(db_chat.id)
    assert await repo.get(db_chat.id) is None


async def test_bulk_create_adds_new(db_session, db_user) -> None:
    repo = ChatRepository(db_session)
    chats = [
        {"chat_id": -5001, "title": "Bulk 1", "username": "bulk1"},
        {"chat_id": -5002, "title": "Bulk 2"},
    ]
    created = await repo.bulk_create(db_user.tg_id, chats)
    assert len(created) == 2
    ids = [c.chat_id for c in created]
    assert -5001 in ids
    assert -5002 in ids


async def test_bulk_create_skips_duplicates(db_session, db_user, db_chat) -> None:
    repo = ChatRepository(db_session)
    chats = [
        {"chat_id": db_chat.chat_id, "title": "Duplicate"},   # existing
        {"chat_id": -6001, "title": "New Chat"},               # new
    ]
    created = await repo.bulk_create(db_user.tg_id, chats)
    assert len(created) == 1
    assert created[0].chat_id == -6001


async def test_bulk_create_empty_list(db_session, db_user) -> None:
    repo = ChatRepository(db_session)
    created = await repo.bulk_create(db_user.tg_id, [])
    assert created == []
