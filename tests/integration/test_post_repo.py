from __future__ import annotations

import uuid

import pytest

from db.models import PostType
from db.repositories.post_repo import PostRepository


pytestmark = pytest.mark.integration


async def test_create_forwarded(db_session, db_user) -> None:
    repo = PostRepository(db_session)
    post = await repo.create_forwarded(db_user.tg_id, "Forwarded Post", -100123, 42)
    assert post.id is not None
    assert post.type == PostType.FORWARDED
    assert post.source_chat_id == -100123
    assert post.source_message_id == 42
    assert post.title == "Forwarded Post"


async def test_create_manual_text(db_session, db_user) -> None:
    repo = PostRepository(db_session)
    post = await repo.create_manual(db_user.tg_id, "Text Post", PostType.TEXT, text="Hello!")
    assert post.type == PostType.TEXT
    assert post.text == "Hello!"
    assert post.media_file_id is None


async def test_create_manual_photo(db_session, db_user) -> None:
    repo = PostRepository(db_session)
    post = await repo.create_manual(
        db_user.tg_id, "Photo Post", PostType.PHOTO,
        text="Caption", media_file_id="FILEID123", media_type="photo"
    )
    assert post.type == PostType.PHOTO
    assert post.media_file_id == "FILEID123"
    assert post.text == "Caption"


async def test_create_manual_with_entities(db_session, db_user) -> None:
    import json
    entities_json = json.dumps([{"offset": 0, "length": 5, "type": "bold"}])
    repo = PostRepository(db_session)
    post = await repo.create_manual(
        db_user.tg_id, "Premium Post", PostType.TEXT,
        text="Bold text", text_entities=entities_json
    )
    assert post.text_entities == entities_json


async def test_get_by_user_ordered_by_date(db_session, db_user) -> None:
    repo = PostRepository(db_session)
    p1 = await repo.create_manual(db_user.tg_id, "Post 1", PostType.TEXT)
    p2 = await repo.create_manual(db_user.tg_id, "Post 2", PostType.TEXT)
    posts = await repo.get_by_user(db_user.tg_id)
    ids = [p.id for p in posts]
    # Most recent first
    assert ids.index(p2.id) < ids.index(p1.id)


async def test_get_post(db_session, db_post) -> None:
    repo = PostRepository(db_session)
    found = await repo.get(db_post.id)
    assert found is not None
    assert found.id == db_post.id


async def test_get_missing_returns_none(db_session) -> None:
    repo = PostRepository(db_session)
    assert await repo.get(uuid.uuid4()) is None


async def test_delete_post(db_session, db_post) -> None:
    repo = PostRepository(db_session)
    await repo.delete(db_post.id)
    assert await repo.get(db_post.id) is None


async def test_delete_missing_noop(db_session) -> None:
    repo = PostRepository(db_session)
    await repo.delete(uuid.uuid4())  # should not raise


async def test_get_by_user_empty_for_other_user(db_session, db_post) -> None:
    repo = PostRepository(db_session)
    posts = await repo.get_by_user(999999)
    assert posts == []
