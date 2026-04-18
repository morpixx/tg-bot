from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

from db.models import Post, PostType, TargetChat, TelegramSession, User
from db.repositories.chat_repo import ChatRepository
from db.repositories.post_repo import PostRepository
from db.repositories.session_repo import SessionRepository
from db.repositories.user_repo import UserRepository

# ── UserRepository ────────────────────────────────────────────────────────────

class TestUserRepo:
    async def test_get_existing(self, mock_db_session) -> None:
        expected = User(tg_id=111)
        mock_db_session.get.return_value = expected
        repo = UserRepository(mock_db_session)
        result = await repo.get(111)
        assert result is expected

    async def test_get_missing_returns_none(self, mock_db_session) -> None:
        mock_db_session.get.return_value = None
        repo = UserRepository(mock_db_session)
        assert await repo.get(999) is None

    async def test_get_or_create_existing(self, mock_db_session) -> None:
        existing = User(tg_id=111)
        mock_db_session.get.return_value = existing
        repo = UserRepository(mock_db_session)
        user, created = await repo.get_or_create(111)
        assert created is False
        assert user is existing

    async def test_get_or_create_new(self, mock_db_session) -> None:
        mock_db_session.get.return_value = None
        repo = UserRepository(mock_db_session)
        user, created = await repo.get_or_create(222, username="newuser")
        assert created is True
        assert user.tg_id == 222
        assert user.username == "newuser"
        mock_db_session.add.assert_called_once()
        mock_db_session.flush.assert_called_once()

    async def test_update_sets_attrs(self, mock_db_session) -> None:
        user = User(tg_id=111, is_active=True)
        mock_db_session.get.return_value = user
        repo = UserRepository(mock_db_session)
        await repo.update(111, is_active=False)
        assert user.is_active is False
        mock_db_session.flush.assert_called_once()

    async def test_update_missing_user_noop(self, mock_db_session) -> None:
        mock_db_session.get.return_value = None
        repo = UserRepository(mock_db_session)
        await repo.update(999, is_active=False)  # should not raise
        mock_db_session.flush.assert_not_called()


# ── SessionRepository ─────────────────────────────────────────────────────────

class TestSessionRepo:
    async def test_create_adds_to_session(self, mock_db_session) -> None:
        sid = uuid.uuid4()
        tg_s = TelegramSession(id=sid, user_id=111, name="Main", encrypted_session="ENC")
        mock_db_session.flush = AsyncMock()

        # Simulate: after add, get returns the new object
        async def fake_flush():
            pass
        mock_db_session.flush.side_effect = fake_flush

        repo = SessionRepository(mock_db_session)
        # We can't test the returned object without real DB flush,
        # so just verify add is called
        with patch_session_model(mock_db_session, tg_s):
            await repo.create(111, "Main", "ENC", phone="+7900", has_premium=True)
        mock_db_session.add.assert_called_once()
        mock_db_session.flush.assert_called_once()

    async def test_delete_calls_delete(self, mock_db_session) -> None:
        sid = uuid.uuid4()
        tg_s = TelegramSession(id=sid, user_id=111, name="Main", encrypted_session="ENC")
        mock_db_session.get.return_value = tg_s
        repo = SessionRepository(mock_db_session)
        await repo.delete(sid)
        mock_db_session.delete.assert_called_once_with(tg_s)
        mock_db_session.flush.assert_called_once()

    async def test_delete_missing_noop(self, mock_db_session) -> None:
        mock_db_session.get.return_value = None
        repo = SessionRepository(mock_db_session)
        await repo.delete(uuid.uuid4())
        mock_db_session.delete.assert_not_called()


# ── PostRepository ────────────────────────────────────────────────────────────

class TestPostRepo:
    async def test_create_forwarded_adds(self, mock_db_session) -> None:
        repo = PostRepository(mock_db_session)
        await repo.create_forwarded(111, "My Post", -100, 42)
        mock_db_session.add.assert_called_once()
        added: Post = mock_db_session.add.call_args[0][0]
        assert added.type == PostType.FORWARDED
        assert added.source_chat_id == -100
        assert added.source_message_id == 42
        assert added.title == "My Post"

    async def test_create_manual_text(self, mock_db_session) -> None:
        repo = PostRepository(mock_db_session)
        await repo.create_manual(111, "Text Post", PostType.TEXT, text="Hello!")
        mock_db_session.add.assert_called_once()
        added: Post = mock_db_session.add.call_args[0][0]
        assert added.type == PostType.TEXT
        assert added.text == "Hello!"

    async def test_delete_existing(self, mock_db_session) -> None:
        pid = uuid.uuid4()
        post = Post(id=pid, user_id=111, title="P", type=PostType.TEXT)
        mock_db_session.get.return_value = post
        repo = PostRepository(mock_db_session)
        await repo.delete(pid)
        mock_db_session.delete.assert_called_once_with(post)


# ── ChatRepository ────────────────────────────────────────────────────────────

class TestChatRepo:
    async def test_create_sets_position(self, mock_db_session) -> None:
        # get_by_user returns empty list (position = 0)
        scalar_result = MagicMock()
        scalar_result.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalar_result
        mock_db_session.execute.return_value = execute_result

        repo = ChatRepository(mock_db_session)
        await repo.create(111, -1001, "Test Chat", "testchat")
        mock_db_session.add.assert_called_once()
        added: TargetChat = mock_db_session.add.call_args[0][0]
        assert added.position == 0
        assert added.chat_id == -1001

    async def test_bulk_create_skips_duplicates(self, mock_db_session) -> None:
        existing_chat = TargetChat(
            id=uuid.uuid4(), user_id=111, chat_id=-1001, title="Existing", position=0
        )
        scalar_result = MagicMock()
        scalar_result.all.return_value = [existing_chat]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalar_result
        mock_db_session.execute.return_value = execute_result

        repo = ChatRepository(mock_db_session)
        chats = [
            {"chat_id": -1001, "title": "Existing"},   # duplicate
            {"chat_id": -1002, "title": "New Chat"},   # new
        ]
        created = await repo.bulk_create(111, chats)
        assert len(created) == 1
        assert created[0].chat_id == -1002


# ── Helpers ───────────────────────────────────────────────────────────────────


@contextmanager
def patch_session_model(mock_session, return_val):
    """Allow flush to not fail when model is referenced."""
    yield
