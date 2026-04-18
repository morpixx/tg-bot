from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from bot.core.config import settings


class IsOwner(BaseFilter):
    """Passes only if the user is the bot owner (OWNER_ID in config)."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user = event.from_user
        return user is not None and user.id == settings.owner_id
