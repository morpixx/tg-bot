from __future__ import annotations

import pytest

from db.repositories.session_repo import SessionRepository

pytestmark = pytest.mark.integration


async def test_create_session(db_session, db_user) -> None:
    repo = SessionRepository(db_session)
    s = await repo.create(
        user_id=db_user.tg_id,
        name="Main Account",
        encrypted_session="FERNET_ENC",
        phone="+79001234567",
        has_premium=True,
        account_name="Ivan",
        account_username="ivan",
    )
    assert s.id is not None
    assert s.name == "Main Account"
    assert s.has_premium is True
    assert s.is_active is True


async def test_get_session(db_session, db_tg_session) -> None:
    repo = SessionRepository(db_session)
    found = await repo.get(db_tg_session.id)
    assert found is not None
    assert found.id == db_tg_session.id


async def test_get_missing_returns_none(db_session) -> None:
    import uuid
    repo = SessionRepository(db_session)
    assert await repo.get(uuid.uuid4()) is None


async def test_get_by_user(db_session, db_user, db_tg_session) -> None:
    repo = SessionRepository(db_session)
    sessions = await repo.get_by_user(db_user.tg_id)
    ids = [s.id for s in sessions]
    assert db_tg_session.id in ids


async def test_get_by_user_excludes_inactive(db_session, db_user, db_tg_session) -> None:
    repo = SessionRepository(db_session)
    await repo.update(db_tg_session.id, is_active=False)
    sessions = await repo.get_by_user(db_user.tg_id)
    ids = [s.id for s in sessions]
    assert db_tg_session.id not in ids


async def test_update_session(db_session, db_tg_session) -> None:
    repo = SessionRepository(db_session)
    await repo.update(db_tg_session.id, has_premium=True, account_name="Updated")
    found = await repo.get(db_tg_session.id)
    assert found.has_premium is True
    assert found.account_name == "Updated"


async def test_delete_session(db_session, db_tg_session) -> None:
    repo = SessionRepository(db_session)
    await repo.delete(db_tg_session.id)
    assert await repo.get(db_tg_session.id) is None


async def test_delete_missing_noop(db_session) -> None:
    import uuid
    repo = SessionRepository(db_session)
    await repo.delete(uuid.uuid4())  # should not raise


async def test_get_all_active(db_session, db_tg_session) -> None:
    repo = SessionRepository(db_session)
    all_active = await repo.get_all_active()
    ids = [s.id for s in all_active]
    assert db_tg_session.id in ids


async def test_get_all_active_excludes_inactive(db_session, db_tg_session) -> None:
    repo = SessionRepository(db_session)
    await repo.update(db_tg_session.id, is_active=False)
    all_active = await repo.get_all_active()
    ids = [s.id for s in all_active]
    assert db_tg_session.id not in ids
