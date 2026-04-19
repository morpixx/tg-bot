from __future__ import annotations

import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.posts_kb import (
    post_add_type_kb,
    post_delete_confirm_kb,
    post_manual_type_kb,
    post_view_kb,
    posts_list_kb,
)
from bot.keyboards.utils import back_kb
from bot.states.fsm import PostAdd
from db.models import PostType, User
from db.repositories.post_repo import PostRepository
from db.session import async_session_factory

router = Router()


@router.callback_query(F.data == "menu:posts")
async def cb_posts_list(callback: CallbackQuery, db_user: User) -> None:
    assert callback.message
    async with async_session_factory() as session:
        repo = PostRepository(session)
        posts = await repo.get_by_user(db_user.tg_id)
    await callback.message.edit_text(
        f"📝 <b>Библиотека постов</b> ({len(posts)})\n\nВыбери пост или добавь новый:",
        reply_markup=posts_list_kb(posts),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("posts:page:"))
async def cb_posts_page(callback: CallbackQuery, db_user: User) -> None:
    assert callback.message and callback.data
    page = int(callback.data.split(":", 2)[2])
    async with async_session_factory() as session:
        repo = PostRepository(session)
        posts = await repo.get_by_user(db_user.tg_id)
    await callback.message.edit_reply_markup(reply_markup=posts_list_kb(posts, page=page))
    await callback.answer()


@router.callback_query(F.data.startswith("post:view:"))
async def cb_post_view(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    post_id = callback.data.split(":", 2)[2]
    async with async_session_factory() as session:
        repo = PostRepository(session)
        post = await repo.get(uuid.UUID(post_id))
    if not post:
        await callback.answer("Пост не найден", show_alert=True)
        return
    type_label = {
        PostType.FORWARDED: "📤 Переслан",
        PostType.TEXT: "📝 Текст",
        PostType.PHOTO: "🖼 Фото",
        PostType.VIDEO: "🎬 Видео",
        PostType.DOCUMENT: "📎 Документ",
        PostType.MEDIA_GROUP: "🗂 Медиагруппа",
    }.get(post.type, "❓")
    text = (
        f"📄 <b>{post.title}</b>\n\n"
        f"Тип: {type_label}\n"
        f"Добавлен: {post.created_at.strftime('%d.%m.%Y %H:%M')}"
    )
    if post.text:
        preview = post.text[:200] + ("..." if len(post.text) > 200 else "")
        text += f"\n\n<i>Превью:</i>\n{preview}"
    await callback.message.edit_text(text, reply_markup=post_view_kb(post_id))
    await callback.answer()


# ── Add post ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "post:add")
async def cb_post_add(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message
    await callback.message.edit_text(
        "➕ <b>Добавить пост</b>\n\nВыбери способ:",
        reply_markup=post_add_type_kb(),
    )
    await state.set_state(PostAdd.waiting_type_choice)
    await callback.answer()


@router.callback_query(F.data == "post:add:forward", PostAdd.waiting_type_choice)
async def cb_post_forward(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message
    await callback.message.edit_text(
        "📤 <b>Форвард из канала</b>\n\n"
        "Перешли сюда любое сообщение из канала/чата.\n"
        "Поддерживаются текст, фото, видео, документы, альбомы."
    )
    await state.set_state(PostAdd.waiting_forward)
    await callback.answer()


@router.message(PostAdd.waiting_forward)
async def fsm_post_receive_forward(message: Message, state: FSMContext) -> None:
    if not message.forward_from_chat and not message.forward_from:
        await message.answer("⚠️ Это не пересланное сообщение. Перешли сообщение из канала:")
        return
    source_chat_id = (
        message.forward_from_chat.id if message.forward_from_chat else None
    )
    source_message_id = message.forward_from_message_id
    if not source_chat_id or not source_message_id:
        await message.answer("⚠️ Не удалось определить источник. Убедись, что пересылаешь из публичного канала.")
        return
    await state.update_data(
        post_type="forwarded",
        source_chat_id=source_chat_id,
        source_message_id=source_message_id,
    )
    await message.answer("📝 Введи название поста для библиотеки (например: «Акция 14 апреля»):")
    await state.set_state(PostAdd.waiting_title)


# ── Manual post ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "post:add:manual", PostAdd.waiting_type_choice)
async def cb_post_manual(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message
    await callback.message.edit_text(
        "✍️ <b>Создать пост вручную</b>\n\nВыбери тип контента:",
        reply_markup=post_manual_type_kb(),
    )
    await state.set_state(PostAdd.waiting_manual_type)
    await callback.answer()


@router.callback_query(F.data.startswith("post:manual:"), PostAdd.waiting_manual_type)
async def cb_post_manual_type(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message and callback.data
    media_type = callback.data.split(":", 2)[2]
    await state.update_data(post_type=media_type)
    prompts = {
        "text": "✍️ Напиши текст поста (поддерживается HTML):",
        "photo": "🖼 Отправь фото с подписью (или без):",
        "video": "🎬 Отправь видео с подписью (или без):",
        "document": "📎 Отправь документ с подписью (или без):",
    }
    await callback.message.edit_text(prompts.get(media_type, "Отправь контент:"))
    await state.set_state(PostAdd.waiting_manual_content)
    await callback.answer()


@router.message(PostAdd.waiting_manual_content)
async def fsm_post_manual_content(message: Message, state: FSMContext) -> None:
    import json
    data = await state.get_data()
    post_type = data.get("post_type", "text")

    if post_type == "text":
        if not message.text:
            await message.answer("⚠️ Нужен текст. Введи текст поста:")
            return
        # Store entities for Premium emoji support
        entities_json = None
        if message.entities:
            entities_json = json.dumps([e.model_dump() for e in message.entities])
        await state.update_data(
            text=message.text,
            text_entities=entities_json,
            media_type=None,
            media_bytes=None,
            media_filename=None,
        )

    elif post_type in ("photo", "video", "document"):
        media = message.photo[-1] if message.photo else (message.video or message.document)
        if not media:
            await message.answer(f"⚠️ Нужен медиафайл типа {post_type}:")
            return
        caption = message.caption or ""
        entities_json = None
        if message.caption_entities:
            entities_json = json.dumps([e.model_dump() for e in message.caption_entities])

        # Download the file now — the worker sends via Telethon (MTProto), which
        # can't consume Bot API file_ids for documents/videos. Storing raw bytes
        # in Postgres lets every session re-upload the same asset cleanly.
        status = await message.answer("⏳ Скачиваю файл...")
        try:
            assert message.bot
            buffer = await message.bot.download(media.file_id)
            media_bytes = buffer.getvalue() if buffer is not None else None
        except Exception as e:
            await status.edit_text(
                f"❌ Не удалось скачать файл: {e}\n\n"
                "Bot API ограничивает размер ~20 МБ. Для крупных файлов используй «Форвард из канала»."
            )
            await state.clear()
            return
        if not media_bytes:
            await status.edit_text("❌ Пустой файл. Попробуй снова.")
            await state.clear()
            return
        try:
            await status.delete()
        except Exception:
            pass

        filename = getattr(media, "file_name", None) or _default_filename(post_type)
        await state.update_data(
            text=caption,
            text_entities=entities_json,
            media_type=post_type,
            media_bytes=media_bytes,
            media_filename=filename,
        )

    await message.answer("📝 Введи название поста для библиотеки:")
    await state.set_state(PostAdd.waiting_title)


def _default_filename(post_type: str) -> str:
    return {"photo": "photo.jpg", "video": "video.mp4", "document": "file.bin"}.get(post_type, "file.bin")


@router.message(PostAdd.waiting_title)
async def fsm_post_title(message: Message, state: FSMContext, db_user: User) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не может быть пустым:")
        return

    data = await state.get_data()
    post_type_str = data.get("post_type", "text")
    await state.clear()

    async with async_session_factory() as session:
        async with session.begin():
            repo = PostRepository(session)
            if post_type_str == "forwarded":
                post = await repo.create_forwarded(
                    user_id=db_user.tg_id,
                    title=title,
                    source_chat_id=data["source_chat_id"],
                    source_message_id=data["source_message_id"],
                )
            else:
                post = await repo.create_manual(
                    user_id=db_user.tg_id,
                    title=title,
                    post_type=PostType(post_type_str),
                    text=data.get("text"),
                    text_entities=data.get("text_entities"),
                    media_type=data.get("media_type"),
                    media_bytes=data.get("media_bytes"),
                    media_filename=data.get("media_filename"),
                )

    await message.answer(
        f"✅ <b>Пост добавлен!</b>\n\n📄 {post.title}",
        reply_markup=back_kb("menu:posts"),
    )


# ── Delete post ───────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("post:delete:confirm_ask:"))
async def cb_post_delete_ask(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    post_id = callback.data.split(":", 3)[3]
    await callback.message.edit_text(
        "🗑 <b>Удалить пост?</b>\n\nКампании, использующие этот пост, продолжат работу, но пост из библиотеки исчезнет.",
        reply_markup=post_delete_confirm_kb(post_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("post:delete:") & ~F.data.startswith("post:delete:confirm_ask:"))
async def cb_post_delete(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    post_id = callback.data.split(":", 2)[2]
    async with async_session_factory() as session:
        async with session.begin():
            repo = PostRepository(session)
            await repo.delete(uuid.UUID(post_id))
    await callback.message.edit_text("✅ Пост удалён.", reply_markup=back_kb("menu:posts"))
    await callback.answer()
