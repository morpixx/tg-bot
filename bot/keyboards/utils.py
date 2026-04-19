from __future__ import annotations

import html

from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message


def esc(s: str | int | None) -> str:
    """HTML-escape user-supplied text for safe interpolation in HTML-mode messages."""
    if s is None:
        return ""
    return html.escape(str(s), quote=False)


def back_button(callback_data: str = "menu:main", text: str = "◀️ Назад") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def cancel_kb(back_to: str = "menu:main", text: str = "❌ Отмена") -> InlineKeyboardMarkup:
    """Single-button cancel keyboard for FSM input prompts."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=back_to)]]
    )


async def reprompt(
    message: Message,
    state: FSMContext,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Edit the prior bot prompt with a validation error and delete the user's invalid input.

    Falls back to a fresh message if the prior prompt cannot be edited (state lost,
    message too old, etc.). Always silently swallows delete failures — the user's
    message just stays if Telegram refuses.

    Requires the spawning handler to have stashed `prompt_message_id` via state.update_data.
    """
    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()
    prompt_id = data.get("prompt_message_id")
    if prompt_id and message.bot:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=prompt_id,
                text=text,
                reply_markup=reply_markup,
            )
            return
        except Exception:
            pass

    sent = await message.answer(text, reply_markup=reply_markup)
    await state.update_data(prompt_message_id=sent.message_id)


async def remember_prompt(state: FSMContext, sent: object) -> None:
    """Stash the bot's prompt message id so future reprompt() calls can edit it.

    Accepts anything with a `message_id` attribute — aiogram's edit_text returns
    Message | bool (True when nothing changed), so we just skip if it's not a Message.
    """
    mid = getattr(sent, "message_id", None)
    if mid is not None:
        await state.update_data(prompt_message_id=mid)


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
