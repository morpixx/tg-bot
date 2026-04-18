from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.core.config import settings
from services.subscription import check_subscriptions, get_channel_invite_links

SUBSCRIBE_TEXT = (
    "🔒 <b>Доступ закрыт</b>\n\n"
    "Для использования бота необходимо подписаться на каналы:\n\n"
    "{links}\n\n"
    "После подписки нажми кнопку ниже 👇"
)


class SubscriptionMiddleware(BaseMiddleware):
    """Block access if user is not subscribed to required channels."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Skip if no channels configured
        if not settings.required_channel_ids:
            return await handler(event, data)

        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        # Owner always has access
        if user.id == settings.owner_id:
            return await handler(event, data)

        # Allow the "I subscribed" re-check callback through unconditionally —
        # otherwise the user is stuck forever (middleware blocks the very button
        # that would let them pass the gate).
        if isinstance(event, CallbackQuery) and event.data == "check_subscription":
            return await handler(event, data)

        bot: Bot = data["bot"]
        subscribed, not_subscribed = await check_subscriptions(bot, user.id)

        if subscribed:
            return await handler(event, data)

        # Build subscription message
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        links = await get_channel_invite_links(bot, not_subscribed)
        link_lines = "\n".join(
            f"• <a href='{url}'>Канал {channel_id}</a>"
            for channel_id, url in links.items()
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")]
            ]
        )
        text = SUBSCRIBE_TEXT.format(links=link_lines)

        if isinstance(event, Message):
            await event.answer(text, reply_markup=keyboard, disable_web_page_preview=True)
        elif isinstance(event, CallbackQuery):
            await event.answer("Сначала подпишитесь на каналы!", show_alert=True)

        return None
