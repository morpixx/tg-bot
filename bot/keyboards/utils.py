from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def back_button(callback_data: str = "menu:main", text: str = "◀️ Назад") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def back_kb(callback_data: str = "menu:main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[back_button(callback_data)]])


def confirm_kb(confirm_data: str, cancel_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data=confirm_data),
                InlineKeyboardButton(text="❌ Отмена", callback_data=cancel_data),
            ]
        ]
    )


def paginate(
    items: list,
    page: int,
    page_size: int = 8,
    callback_prefix: str = "page",
) -> tuple[list, InlineKeyboardMarkup | None]:
    """Return items slice and pagination keyboard."""
    total = len(items)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    sliced = items[page * page_size : (page + 1) * page_size]

    if total_pages <= 1:
        return sliced, None

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀", callback_data=f"{callback_prefix}:{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶", callback_data=f"{callback_prefix}:{page + 1}"))

    kb = InlineKeyboardMarkup(inline_keyboard=[nav_buttons])
    return sliced, kb
