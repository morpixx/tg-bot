from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.utils import back_button
from db.models import TelegramSession


def phone_retry_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Попробовать снова", callback_data="session:add:phone")],
            [InlineKeyboardButton(text="📷 Войти по QR", callback_data="session:add:qr")],
            [back_button("menu:sessions")],
        ]
    )


def sessions_list_kb(sessions: list[TelegramSession]) -> InlineKeyboardMarkup:
    rows = []
    for s in sessions:
        premium = " 💎" if s.has_premium else ""
        label = f"{'🟢' if s.is_active else '🔴'} {s.name}{premium}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"session:view:{s.id}")])
    rows.append([InlineKeyboardButton(text="➕ Добавить сессию", callback_data="session:add")])
    rows.append([back_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def session_add_method_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📷 QR-код / ссылка", callback_data="session:add:qr")],
            [InlineKeyboardButton(text="📞 Номер телефона", callback_data="session:add:phone")],
            [back_button("menu:sessions")],
        ]
    )


def qr_auth_kb(login_url: str) -> InlineKeyboardMarkup:
    """QR screen controls: clickable tg://login link + cancel.

    Token auto-refreshes in the background, so a manual refresh button
    would just add UI noise.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔓 Авторизовать по ссылке", url=login_url)],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="session:qr:cancel")],
        ]
    )


def session_view_kb(session_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"session:rename:{session_id}"),
                InlineKeyboardButton(text="🔄 Проверить", callback_data=f"session:check:{session_id}"),
            ],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"session:delete:{session_id}")],
            [back_button("menu:sessions")],
        ]
    )


def session_confirm_delete_kb(session_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"session:delete:confirm:{session_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"session:view:{session_id}"),
            ]
        ]
    )
