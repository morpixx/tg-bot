from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.utils import back_button
from db.models import Post


def posts_list_kb(posts: list[Post], page: int = 0) -> InlineKeyboardMarkup:
    from bot.keyboards.utils import paginate
    sliced, page_kb = paginate(posts, page, page_size=8, callback_prefix="posts:page")
    rows = []
    for p in sliced:
        emoji = {"forwarded": "📤", "text": "📝", "photo": "🖼", "video": "🎬", "document": "📎", "media_group": "🗂"}.get(p.type.value, "📄")
        rows.append([InlineKeyboardButton(text=f"{emoji} {p.title}", callback_data=f"post:view:{p.id}")])
    if page_kb:
        rows.extend(page_kb.inline_keyboard)
    rows.append([InlineKeyboardButton(text="➕ Добавить пост", callback_data="post:add")])
    rows.append([back_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def post_add_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 Переслать из канала", callback_data="post:add:forward")],
            [InlineKeyboardButton(text="✍️ Создать вручную", callback_data="post:add:manual")],
            [back_button("menu:posts")],
        ]
    )


def post_manual_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Текст", callback_data="post:manual:text")],
            [InlineKeyboardButton(text="🖼 Фото + подпись", callback_data="post:manual:photo")],
            [InlineKeyboardButton(text="🎬 Видео + подпись", callback_data="post:manual:video")],
            [InlineKeyboardButton(text="📎 Документ + подпись", callback_data="post:manual:document")],
            [back_button("post:add")],
        ]
    )


def post_view_kb(post_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"post:delete:{post_id}")],
            [back_button("menu:posts")],
        ]
    )
