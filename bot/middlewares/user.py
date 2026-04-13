from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from db.repositories.user_repo import UserRepository
from db.session import async_session_factory


class UserMiddleware(BaseMiddleware):
    """Auto-register user on first interaction and inject into handler data."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        async with async_session_factory() as session:
            async with session.begin():
                repo = UserRepository(session)
                db_user, _ = await repo.get_or_create(
                    tg_id=user.id,
                    username=user.username,
                    full_name=user.full_name,
                )
                data["db_user"] = db_user
                data["db_session"] = session
                return await handler(event, data)
