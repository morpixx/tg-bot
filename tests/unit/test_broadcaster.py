from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import BroadcastStatus, PostType
from worker.broadcaster import Broadcaster, get_progress, request_stop
from worker.session_pool import SessionPool


# ── Stop signals ──────────────────────────────────────────────────────────────

class TestStopSignals:
    def test_request_stop_sets_signal(self) -> None:
        from worker.broadcaster import _stop_signals
        cid = uuid.uuid4()
        request_stop(cid)
        assert _stop_signals.get(cid) is True

    def test_get_progress_default(self) -> None:
        cid = uuid.uuid4()
        assert get_progress(cid) == (0, 0)

    def test_get_progress_after_set(self) -> None:
        from worker.broadcaster import _progress
        cid = uuid.uuid4()
        _progress[cid] = (5, 10)
        assert get_progress(cid) == (5, 10)
        del _progress[cid]


# ── _send_post ────────────────────────────────────────────────────────────────

class TestSendPost:
    @pytest.fixture
    def broadcaster(self) -> Broadcaster:
        pool = MagicMock(spec=SessionPool)
        return Broadcaster(pool)

    def _make_post(self, post_type: PostType, **kwargs) -> MagicMock:
        post = MagicMock()
        post.type = post_type
        post.source_chat_id = -100
        post.source_message_id = 42
        post.text = "Hello"
        post.text_entities = None
        post.media_file_id = "FILE123"
        for k, v in kwargs.items():
            setattr(post, k, v)
        return post

    def _make_client(self) -> AsyncMock:
        client = AsyncMock()
        msg = MagicMock()
        msg.id = 999
        client.forward_messages.return_value = [msg]
        client.send_message.return_value = msg
        client.send_file.return_value = msg
        msg2 = MagicMock()
        msg2.message = "text"
        msg2.media = None
        msg2.entities = None
        client.get_messages.return_value = msg2
        return client

    async def test_forwarded_forward_mode(self, broadcaster) -> None:
        client = self._make_client()
        post = self._make_post(PostType.FORWARDED)
        status, msg_id, error = await broadcaster._send_post(client, post, -200, forward_mode=True)
        assert status == BroadcastStatus.SUCCESS
        assert msg_id == 999
        assert error is None
        client.forward_messages.assert_called_once()

    async def test_forwarded_copy_mode(self, broadcaster) -> None:
        client = self._make_client()
        post = self._make_post(PostType.FORWARDED)
        status, msg_id, error = await broadcaster._send_post(client, post, -200, forward_mode=False)
        assert status == BroadcastStatus.SUCCESS
        client.get_messages.assert_called_once()
        client.send_message.assert_called_once()

    async def test_forwarded_copy_source_not_found(self, broadcaster) -> None:
        client = self._make_client()
        client.get_messages.return_value = None
        post = self._make_post(PostType.FORWARDED)
        status, msg_id, error = await broadcaster._send_post(client, post, -200, forward_mode=False)
        assert status == BroadcastStatus.SKIPPED
        assert error == "Source message not found"

    async def test_text_post(self, broadcaster) -> None:
        client = self._make_client()
        post = self._make_post(PostType.TEXT)
        status, msg_id, error = await broadcaster._send_post(client, post, -200, forward_mode=True)
        assert status == BroadcastStatus.SUCCESS
        client.send_message.assert_called_once()

    async def test_photo_post(self, broadcaster) -> None:
        client = self._make_client()
        post = self._make_post(PostType.PHOTO)
        status, msg_id, error = await broadcaster._send_post(client, post, -200, forward_mode=True)
        assert status == BroadcastStatus.SUCCESS
        client.send_file.assert_called_once()

    async def test_video_post(self, broadcaster) -> None:
        client = self._make_client()
        post = self._make_post(PostType.VIDEO)
        status, msg_id, error = await broadcaster._send_post(client, post, -200, forward_mode=True)
        assert status == BroadcastStatus.SUCCESS
        client.send_file.assert_called_once()

    async def test_document_post(self, broadcaster) -> None:
        client = self._make_client()
        post = self._make_post(PostType.DOCUMENT)
        status, msg_id, error = await broadcaster._send_post(client, post, -200, forward_mode=True)
        assert status == BroadcastStatus.SUCCESS
        client.send_file.assert_called_once()

    async def test_flood_wait_handled(self, broadcaster) -> None:
        from telethon.errors import FloodWaitError
        client = self._make_client()
        exc = FloodWaitError(request=MagicMock())
        exc.seconds = 5
        client.send_message.side_effect = exc
        post = self._make_post(PostType.TEXT)

        with patch("asyncio.sleep", AsyncMock()):
            status, msg_id, error = await broadcaster._send_post(client, post, -200, forward_mode=True)

        assert status == BroadcastStatus.FLOOD_WAIT
        assert "FloodWait" in (error or "")
        assert msg_id is None

    async def test_chat_write_forbidden_skipped(self, broadcaster) -> None:
        from telethon.errors import ChatWriteForbiddenError
        client = self._make_client()
        client.send_message.side_effect = ChatWriteForbiddenError(request=MagicMock())
        post = self._make_post(PostType.TEXT)
        status, msg_id, error = await broadcaster._send_post(client, post, -200, forward_mode=True)
        assert status == BroadcastStatus.SKIPPED

    async def test_generic_exception_failed(self, broadcaster) -> None:
        client = self._make_client()
        client.send_message.side_effect = RuntimeError("network error")
        post = self._make_post(PostType.TEXT)
        status, msg_id, error = await broadcaster._send_post(client, post, -200, forward_mode=True)
        assert status == BroadcastStatus.FAILED
        assert "network error" in (error or "")

    async def test_text_with_entities_json(self, broadcaster) -> None:
        """Entities JSON is parsed and passed to send_message."""
        import json
        client = self._make_client()
        post = self._make_post(PostType.TEXT)
        # Use aiogram-style entities (lowercase 'type')
        post.text_entities = json.dumps([{"type": "bold", "offset": 0, "length": 5}])

        status, _, _ = await broadcaster._send_post(client, post, -200, forward_mode=True)
        assert status == BroadcastStatus.SUCCESS
        # Check that formatting_entities was passed
        client.send_message.assert_called_once()
        args, kwargs = client.send_message.call_args
        assert kwargs["formatting_entities"] is not None
        assert len(kwargs["formatting_entities"]) == 1
