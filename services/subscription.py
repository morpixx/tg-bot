from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from bot.core.config import settings
from services.cache import channel_info_cache, subscription_cache


async def check_subscriptions(bot: Bot, user_id: int) -> tuple[bool, list[int]]:
    """
    Check if user is subscribed to all required channels.
    Returns (all_subscribed, list_of_not_subscribed_channel_ids).
    Result is cached per user for ~30s (services.cache.subscription_cache).
    """
    if not settings.required_channel_ids:
        return True, []

    cached = subscription_cache.get(user_id)
    if cached is not None:
        return cached

    not_subscribed: list[int] = []
    for channel_id in settings.required_channel_ids:
        try:
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            if member.status in ("left", "kicked"):
                not_subscribed.append(channel_id)
        except (TelegramForbiddenError, TelegramBadRequest):
            pass

    result = (len(not_subscribed) == 0, not_subscribed)
    subscription_cache[user_id] = result
    return result


async def get_channel_info(bot: Bot, channel_id: int) -> tuple[str, str]:
    """Return (title, invite_url) for a channel. Cached ~10 min."""
    cached = channel_info_cache.get(channel_id)
    if cached is not None:
        return cached

    title = f"Канал {channel_id}"
    url = str(channel_id)
    try:
        chat = await bot.get_chat(channel_id)
        title = chat.title or title
        if chat.username:
            url = f"https://t.me/{chat.username}"
        else:
            link = await bot.create_chat_invite_link(channel_id)
            url = link.invite_link
    except Exception:
        pass

    channel_info_cache[channel_id] = (title, url)
    return title, url


async def get_channel_invite_links(bot: Bot, channel_ids: list[int]) -> dict[int, tuple[str, str]]:
    """Fetch (title, url) per channel. Used by the subscription gate."""
    result: dict[int, tuple[str, str]] = {}
    for cid in channel_ids:
        result[cid] = await get_channel_info(bot, cid)
    return result
