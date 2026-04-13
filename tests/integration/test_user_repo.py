from __future__ import annotations

import pytest

from db.repositories.user_repo import UserRepository


pytestmark = pytest.mark.integration


async def test_get_or_create_new(db_session) -> None:
    repo = UserRepository(db_session)
    user, created = await repo.get_or_create(99999001, username="newop", full_name="New Op")
    assert created is True
    assert user.tg_id == 99999001
    assert user.username == "newop"


async def test_get_or_create_existing(db_session, db_user) -> None:
    repo = UserRepository(db_session)
    user2, created = await repo.get_or_create(db_user.tg_id)
    assert created is False
    assert user2.tg_id == db_user.tg_id


async def test_get_existing(db_session, db_user) -> None:
    repo = UserRepository(db_session)
    found = await repo.get(db_user.tg_id)
    assert found is not None
    assert found.tg_id == db_user.tg_id


async def test_get_missing_returns_none(db_session) -> None:
    repo = UserRepository(db_session)
    assert await repo.get(0) is None


async def test_update_fields(db_session, db_user) -> None:
    repo = UserRepository(db_session)
    await repo.update(db_user.tg_id, is_active=False, username="updated")
    found = await repo.get(db_user.tg_id)
    assert found.is_active is False
    assert found.username == "updated"


async def test_update_missing_user_noop(db_session) -> None:
    repo = UserRepository(db_session)
    await repo.update(0, is_active=False)  # should not raise


async def test_list_active_includes_active(db_session, db_user) -> None:
    repo = UserRepository(db_session)
    users = await repo.list_active()
    ids = [u.tg_id for u in users]
    assert db_user.tg_id in ids


async def test_list_active_excludes_inactive(db_session, db_user) -> None:
    repo = UserRepository(db_session)
    await repo.update(db_user.tg_id, is_active=False)
    users = await repo.list_active()
    ids = [u.tg_id for u in users]
    assert db_user.tg_id not in ids
