from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Message


async def _call_middleware(middleware, event, data: dict):
    handler = AsyncMock(return_value="handled")
    return await middleware(handler, event, data)


# ── UserMiddleware ────────────────────────────────────────────────────────────

class TestUserMiddleware:
    async def test_no_user_skips_db(self) -> None:
        from bot.middlewares.user import UserMiddleware
        mw = UserMiddleware()
        event = MagicMock()
        data = {}  # no event_from_user
        result = await _call_middleware(mw, event, data)
        assert result == "handled"

    async def test_creates_user_on_first_visit(self) -> None:
        from bot.middlewares.user import UserMiddleware
        from db.models import User

        mw = UserMiddleware()
        user = MagicMock()
        user.id = 555
        user.username = "newuser"
        user.full_name = "New User"

        db_user = User(tg_id=555, username="newuser")
        mock_repo = AsyncMock()
        mock_repo.get_or_create.return_value = (db_user, True)

        event = MagicMock()
        data = {"event_from_user": user}

        with (
            patch("bot.middlewares.user.async_session_factory") as mock_factory,
            patch("bot.middlewares.user.UserRepository", return_value=mock_repo),
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session.begin = MagicMock(return_value=mock_session)
            mock_factory.return_value = mock_session

            handler = AsyncMock(return_value="ok")
            result = await mw(handler, event, data)

        assert result == "ok"


# ── SubscriptionMiddleware ────────────────────────────────────────────────────

class TestSubscriptionMiddleware:
    async def test_no_channels_passes_through(self) -> None:
        from bot.middlewares.subscription import SubscriptionMiddleware
        mw = SubscriptionMiddleware()

        with patch("bot.middlewares.subscription.settings") as s:
            s.required_channel_ids = []
            s.owner_id = 999
            event = MagicMock(spec=Message)
            data = {"event_from_user": MagicMock(id=111), "bot": AsyncMock()}
            result = await _call_middleware(mw, event, data)

        assert result == "handled"

    async def test_owner_always_passes(self) -> None:
        from bot.middlewares.subscription import SubscriptionMiddleware
        mw = SubscriptionMiddleware()

        with patch("bot.middlewares.subscription.settings") as s:
            s.required_channel_ids = [-1001]
            s.owner_id = 999
            event = MagicMock()
            data = {"event_from_user": MagicMock(id=999), "bot": AsyncMock()}
            result = await _call_middleware(mw, event, data)

        assert result == "handled"

    async def test_subscribed_user_passes(self) -> None:
        from bot.middlewares.subscription import SubscriptionMiddleware
        mw = SubscriptionMiddleware()

        with (
            patch("bot.middlewares.subscription.settings") as s,
            patch("bot.middlewares.subscription.check_subscriptions", return_value=(True, [])),
        ):
            s.required_channel_ids = [-1001]
            s.owner_id = 999
            event = MagicMock()
            data = {"event_from_user": MagicMock(id=111), "bot": AsyncMock()}
            result = await _call_middleware(mw, event, data)

        assert result == "handled"

    async def test_unsubscribed_message_blocked(self) -> None:
        from bot.middlewares.subscription import SubscriptionMiddleware
        mw = SubscriptionMiddleware()

        with (
            patch("bot.middlewares.subscription.settings") as s,
            patch("bot.middlewares.subscription.check_subscriptions", return_value=(False, [-1001])),
            patch("bot.middlewares.subscription.get_channel_invite_links", return_value={-1001: "https://t.me/test"}),
        ):
            s.required_channel_ids = [-1001]
            s.owner_id = 999

            event = AsyncMock(spec=Message)
            event.answer = AsyncMock()
            data = {"event_from_user": MagicMock(id=111), "bot": AsyncMock()}
            result = await mw(AsyncMock(), event, data)

        # Blocked — returns None
        assert result is None
        event.answer.assert_called_once()

    async def test_no_event_from_user_skips(self) -> None:
        from bot.middlewares.subscription import SubscriptionMiddleware
        mw = SubscriptionMiddleware()

        with patch("bot.middlewares.subscription.settings") as s:
            s.required_channel_ids = [-1001]
            data = {}  # no event_from_user
            result = await _call_middleware(mw, MagicMock(), data)

        assert result == "handled"
