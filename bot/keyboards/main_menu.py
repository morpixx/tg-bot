from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_kb(is_owner: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="📱 Сессии", callback_data="menu:sessions"),
            InlineKeyboardButton(text="📝 Посты", callback_data="menu:posts"),
        ],
        [
            InlineKeyboardButton(text="💬 Чаты", callback_data="menu:chats"),
            InlineKeyboardButton(text="📢 Кампании", callback_data="menu:campaigns"),
        ],
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings"),
        ],
    ]
    if is_owner:
        rows.append([InlineKeyboardButton(text="🔧 Панель владельца", callback_data="admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
