from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from cachetools import TTLCache  # type: ignore[import-untyped]


class ThrottleMiddleware(BaseMiddleware):
    """Simple in-memory rate limiter: 1 message per `rate` seconds per user."""

    def __init__(self, rate: float = 0.5) -> None:
        self._cache: TTLCache = TTLCache(maxsize=10_000, ttl=rate)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        if user.id in self._cache:
            return None

        self._cache[user.id] = True
        return await handler(event, data)
