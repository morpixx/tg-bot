from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    KeyboardButtonRequestChat,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from bot.keyboards.utils import back_button


def chat_add_method_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📲 Выбрать из своих чатов", callback_data="chat:add:picker")],
            [InlineKeyboardButton(text="📤 Переслать сообщение", callback_data="chat:add:forward")],
            [InlineKeyboardButton(text="🔗 Ссылка / @username / ID", callback_data="chat:add:link")],
            [back_button("menu:chats")],
        ]
    )


def chat_picker_reply_kb() -> ReplyKeyboardMarkup:
    """Native Telegram chat picker (Bot API 7.0+).

    User taps the button → Telegram opens an in-app chat picker filtered to
    groups+channels. Bot receives a `message.chat_shared` update with the
    chat_id and title (no manual typing needed).
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="📢 Канал",
                    request_chat=KeyboardButtonRequestChat(
                        request_id=1,
                        chat_is_channel=True,
                        request_title=True,
                        request_username=True,
                    ),
                ),
                KeyboardButton(
                    text="👥 Группа",
                    request_chat=KeyboardButtonRequestChat(
                        request_id=2,
                        chat_is_channel=False,
                        request_title=True,
                        request_username=True,
                    ),
                ),
            ],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        is_persistent=False,
    )


def remove_reply_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
