from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from db.repositories.user_repo import UserRepository
from db.session import async_session_factory
from services.cache import user_cache


class UserMiddleware(BaseMiddleware):
    """Auto-register user on first interaction and inject into handler data.

    The upserted User row is cached in-memory for ~60s (services.cache.user_cache).
    This skips a DB round-trip on every hot-path interaction while still letting
    username / full_name changes propagate within a minute.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        cached = user_cache.get(user.id)
        if cached is not None:
            data["db_user"] = cached
            return await handler(event, data)

        async with async_session_factory() as session:
            async with session.begin():
                repo = UserRepository(session)
                db_user, _ = await repo.get_or_create(
                    tg_id=user.id,
                    username=user.username,
                    full_name=user.full_name,
                )
            session.expunge(db_user)

        user_cache[user.id] = db_user
        data["db_user"] = db_user
        return await handler(event, data)
