from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from bot.core.config import settings


async def check_subscriptions(bot: Bot, user_id: int) -> tuple[bool, list[int]]:
    """
    Check if user is subscribed to all required channels.
    Returns (all_subscribed, list_of_not_subscribed_channel_ids).
    """
    if not settings.required_channel_ids:
        return True, []

    not_subscribed: list[int] = []
    for channel_id in settings.required_channel_ids:
        try:
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            if member.status in ("left", "kicked", "banned"):
                not_subscribed.append(channel_id)
        except (TelegramForbiddenError, TelegramBadRequest):
            # Bot is not in channel or channel doesn't exist — skip
            pass

    return len(not_subscribed) == 0, not_subscribed


async def get_channel_invite_links(bot: Bot, channel_ids: list[int]) -> dict[int, str]:
    """Get invite links for channels. Falls back to t.me/username if available."""
    links: dict[int, str] = {}
    for channel_id in channel_ids:
        try:
            chat = await bot.get_chat(channel_id)
            if chat.username:
                links[channel_id] = f"https://t.me/{chat.username}"
            else:
                link = await bot.create_chat_invite_link(channel_id)
                links[channel_id] = link.invite_link
        except Exception:
            links[channel_id] = str(channel_id)
    return links
