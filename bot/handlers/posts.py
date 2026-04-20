from __future__ import annotations

import asyncio
import json
import uuid

import structlog
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
from bot.keyboards.utils import back_kb, cancel_kb, esc, remember_prompt, reprompt
from bot.states.fsm import PostAdd
from db.models import PostType, User
from db.repositories.post_repo import PostRepository
from db.session import async_session_factory

router = Router()
log = structlog.get_logger()

# Media bytes can't travel through Redis FSM (JSON-serialized). Stash them
# in-process between the "upload media" and "give it a title" steps, keyed
# by user id. Cleared on completion or when overwritten by a new flow.
_pending_media: dict[int, dict] = {}

# Telegram delivers an album as N separate Message updates with the same
# media_group_id. We buffer them for a short debounce window, then process
# the whole batch once the last one has arrived.
_album_buffers: dict[str, dict] = {}
_ALBUM_DEBOUNCE_SECONDS = 1.2


@router.callback_query(F.data == "menu:posts")
async def cb_posts_list(callback: CallbackQuery, db_user: User) -> None:
    if not callback.message:
        await callback.answer()
        return
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
    if not callback.message or not callback.data:
        await callback.answer()
        return
    page = int(callback.data.split(":", 2)[2])
    async with async_session_factory() as session:
        repo = PostRepository(session)
        posts = await repo.get_by_user(db_user.tg_id)
    await callback.message.edit_reply_markup(reply_markup=posts_list_kb(posts, page=page))
    await callback.answer()


@router.callback_query(F.data.startswith("post:view:"))
async def cb_post_view(callback: CallbackQuery) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    post_id = callback.data.split(":", 2)[2]
    async with async_session_factory() as session:
        repo = PostRepository(session)
        post = await repo.get(uuid.UUID(post_id))
        items_count = 0
        if post and post.type == PostType.MEDIA_GROUP:
            items_count = await repo.count_media_items(post.id)
    if not post:
        await callback.answer("Пост не найден", show_alert=True)
        return
    type_label = {
        PostType.FORWARDED: "📤 Переслан",
        PostType.TEXT: "📝 Текст",
        PostType.PHOTO: "🖼 Фото",
        PostType.VIDEO: "🎬 Видео",
        PostType.DOCUMENT: "📎 Документ",
        PostType.MEDIA_GROUP: f"🗂 Альбом ({items_count})",
    }.get(post.type, "❓")
    text = (
        f"📄 <b>{esc(post.title)}</b>\n\n"
        f"Тип: {type_label}\n"
        f"Добавлен: {post.created_at.strftime('%d.%m.%Y %H:%M')}"
    )
    if post.text:
        preview = post.text[:200] + ("..." if len(post.text) > 200 else "")
        text += f"\n\n<i>Превью:</i>\n{esc(preview)}"
    await callback.message.edit_text(text, reply_markup=post_view_kb(post_id))
    await callback.answer()


# ── Add post ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "post:add")
async def cb_post_add(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return
    await callback.message.edit_text(
        "➕ <b>Добавить пост</b>\n\nВыбери способ:",
        reply_markup=post_add_type_kb(),
    )
    await state.set_state(PostAdd.waiting_type_choice)
    await callback.answer()


@router.callback_query(F.data == "post:add:forward", PostAdd.waiting_type_choice)
async def cb_post_forward(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return
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
        await reprompt(message, state, "⚠️ Это не пересланное сообщение. Перешли сообщение из канала:", reply_markup=cancel_kb("menu:posts"))
        return
    source_chat_id = (
        message.forward_from_chat.id if message.forward_from_chat else None
    )
    source_message_id = message.forward_from_message_id
    if not source_chat_id or not source_message_id:
        await reprompt(message, state, "⚠️ Не удалось определить источник. Убедись, что пересылаешь из публичного канала.", reply_markup=cancel_kb("menu:posts"))
        return
    await state.update_data(
        post_type="forwarded",
        source_chat_id=source_chat_id,
        source_message_id=source_message_id,
    )
    sent = await message.answer(
        "📝 Введи название поста для библиотеки (например: «Акция 14 апреля»):",
        reply_markup=cancel_kb("menu:posts"),
    )
    await remember_prompt(state, sent)
    await state.set_state(PostAdd.waiting_title)


# ── Manual post ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "post:add:manual", PostAdd.waiting_type_choice)
async def cb_post_manual(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return
    await callback.message.edit_text(
        "✍️ <b>Создать пост вручную</b>\n\nВыбери тип контента:",
        reply_markup=post_manual_type_kb(),
    )
    await state.set_state(PostAdd.waiting_manual_type)
    await callback.answer()


@router.callback_query(F.data.startswith("post:manual:"), PostAdd.waiting_manual_type)
async def cb_post_manual_type(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    media_type = callback.data.split(":", 2)[2]
    await state.update_data(post_type=media_type)
    prompts = {
        "text": "✍️ Напиши текст поста (поддерживается HTML):",
        "photo": "🖼 Отправь фото с подписью (или без).\n\nМожно прислать альбомом — до 10 файлов.",
        "video": "🎬 Отправь видео с подписью (или без).\n\nМожно прислать альбомом — до 10 файлов.",
        "document": "📎 Отправь документ с подписью (или без).\n\nМожно прислать альбомом — до 10 файлов.",
    }
    await callback.message.edit_text(prompts.get(media_type, "Отправь контент:"))
    await state.set_state(PostAdd.waiting_manual_content)
    await callback.answer()


@router.message(PostAdd.waiting_manual_content)
async def fsm_post_manual_content(message: Message, state: FSMContext) -> None:
    assert message.from_user
    user_id = message.from_user.id

    # Album path: Telegram splits it across N messages with the same
    # media_group_id. Buffer them all and process once the stream settles.
    if message.media_group_id:
        await _accept_album_message(message, state)
        return

    data = await state.get_data()
    post_type = data.get("post_type", "text")

    if post_type == "text":
        if not message.text:
            await reprompt(message, state, "⚠️ Нужен текст. Введи текст поста:", reply_markup=cancel_kb("menu:posts"))
            return
        # Store entities for Premium emoji support
        entities_json = None
        if message.entities:
            entities_json = json.dumps([e.model_dump() for e in message.entities])
        _pending_media.pop(user_id, None)
        await state.update_data(
            text=message.text,
            text_entities=entities_json,
            media_type=None,
            media_filename=None,
        )

    elif post_type in ("photo", "video", "document"):
        media = message.photo[-1] if message.photo else (message.video or message.document)
        if not media:
            await reprompt(message, state, f"⚠️ Нужен медиафайл типа {post_type}:", reply_markup=cancel_kb("menu:posts"))
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
        # Keep bytes off FSM (Redis/JSON can't serialize them); stash in-process.
        _pending_media[user_id] = {"bytes": media_bytes, "filename": filename}
        await state.update_data(
            text=caption,
            text_entities=entities_json,
            media_type=post_type,
            media_filename=filename,
        )

    sent = await message.answer(
        "📝 Введи название поста для библиотеки:",
        reply_markup=cancel_kb("menu:posts"),
    )
    await remember_prompt(state, sent)
    await state.set_state(PostAdd.waiting_title)


def _default_filename(post_type: str) -> str:
    return {"photo": "photo.jpg", "video": "video.mp4", "document": "file.bin"}.get(post_type, "file.bin")


# ── Album buffering ───────────────────────────────────────────────────────────

async def _accept_album_message(message: Message, state: FSMContext) -> None:
    """Stash one album message and (re)start the debounce that finalizes it."""
    assert message.from_user
    mgid = message.media_group_id
    assert mgid

    buf = _album_buffers.get(mgid)
    if buf is None:
        buf = {
            "messages": [message],
            "user_id": message.from_user.id,
            "chat_id": message.chat.id,
            "state": state,
            "task": None,
        }
        _album_buffers[mgid] = buf
    else:
        buf["messages"].append(message)

    task = buf.get("task")
    if task and not task.done():
        task.cancel()
    buf["task"] = asyncio.create_task(_finalize_album(mgid))


async def _finalize_album(mgid: str) -> None:
    """Wait for the album to settle, download all items, advance to title step."""
    try:
        await asyncio.sleep(_ALBUM_DEBOUNCE_SECONDS)
    except asyncio.CancelledError:
        return

    buf = _album_buffers.pop(mgid, None)
    if not buf:
        return

    messages: list[Message] = buf["messages"]
    state: FSMContext = buf["state"]
    user_id: int = buf["user_id"]
    chat_id: int = buf["chat_id"]
    first = messages[0]
    assert first.bot

    status = await first.bot.send_message(chat_id, "⏳ Скачиваю альбом...")

    items: list[dict] = []
    for idx, m in enumerate(messages):
        media = m.photo[-1] if m.photo else (m.video or m.document)
        if not media:
            continue
        mtype = "photo" if m.photo else ("video" if m.video else "document")
        try:
            buf_obj = await m.bot.download(media.file_id)
            blob = buf_obj.getvalue() if buf_obj is not None else None
        except Exception as e:
            log.warning("Album item download failed", idx=idx, error=str(e))
            blob = None
        if not blob:
            continue
        filename = getattr(media, "file_name", None) or _default_filename(mtype)
        items.append({"type": mtype, "bytes": blob, "filename": filename})

    if not items:
        try:
            await status.edit_text(
                "❌ Не удалось скачать медиа. Попробуй снова — Bot API "
                "ограничивает файлы ~20 МБ."
            )
        except Exception:
            pass
        await state.clear()
        return

    caption = ""
    caption_entities_raw = None
    for m in messages:
        if m.caption:
            caption = m.caption
            caption_entities_raw = m.caption_entities
            break
    entities_json = (
        json.dumps([e.model_dump() for e in caption_entities_raw])
        if caption_entities_raw else None
    )

    _pending_media[user_id] = {"items": items}
    await state.update_data(
        post_type="media_group",
        text=caption,
        text_entities=entities_json,
        media_type=None,
        media_filename=None,
    )

    try:
        await status.delete()
    except Exception:
        pass

    sent = await first.bot.send_message(
        chat_id,
        f"🗂 Альбом из {len(items)} элементов принят.\n\n"
        "📝 Введи название поста для библиотеки:",
        reply_markup=cancel_kb("menu:posts"),
    )
    await remember_prompt(state, sent)
    await state.set_state(PostAdd.waiting_title)


@router.message(PostAdd.waiting_title)
async def fsm_post_title(message: Message, state: FSMContext, db_user: User) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не может быть пустым:")
        return

    assert message.from_user
    data = await state.get_data()
    post_type_str = data.get("post_type", "text")
    pending = _pending_media.pop(message.from_user.id, None)
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
            elif post_type_str == "media_group":
                post = await repo.create_media_group(
                    user_id=db_user.tg_id,
                    title=title,
                    text=data.get("text"),
                    text_entities=data.get("text_entities"),
                    items=(pending or {}).get("items") or [],
                )
            else:
                post = await repo.create_manual(
                    user_id=db_user.tg_id,
                    title=title,
                    post_type=PostType(post_type_str),
                    text=data.get("text"),
                    text_entities=data.get("text_entities"),
                    media_type=data.get("media_type"),
                    media_bytes=(pending or {}).get("bytes"),
                    media_filename=data.get("media_filename") or (pending or {}).get("filename"),
                )

    await message.answer(
        f"✅ <b>Пост добавлен!</b>\n\n📄 {esc(post.title)}",
        reply_markup=back_kb("menu:posts"),
    )


# ── Delete post ───────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("post:delete:confirm_ask:"))
async def cb_post_delete_ask(callback: CallbackQuery) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    post_id = callback.data.split(":", 3)[3]
    async with async_session_factory() as session:
        repo = PostRepository(session)
        in_use = await repo.count_campaigns(uuid.UUID(post_id))
    if in_use > 0:
        await callback.message.edit_text(
            f"⚠️ <b>Нельзя удалить.</b>\n\n"
            f"Пост используется в {in_use} кампани{'и' if in_use == 1 else 'ях'}. "
            f"Сначала удали эти кампании.",
            reply_markup=back_kb(f"post:view:{post_id}"),
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        "🗑 <b>Удалить пост?</b>\n\nЭто действие нельзя отменить.",
        reply_markup=post_delete_confirm_kb(post_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("post:delete:") & ~F.data.startswith("post:delete:confirm_ask:"))
async def cb_post_delete(callback: CallbackQuery) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    post_id = callback.data.split(":", 2)[2]
    async with async_session_factory() as session:
        async with session.begin():
            repo = PostRepository(session)
            in_use = await repo.count_campaigns(uuid.UUID(post_id))
            if in_use > 0:
                await callback.message.edit_text(
                    f"⚠️ Пост используется в {in_use} кампани{'и' if in_use == 1 else 'ях'} — сначала удали их.",
                    reply_markup=back_kb(f"post:view:{post_id}"),
                )
                await callback.answer()
                return
            await repo.delete(uuid.UUID(post_id))
    await callback.message.edit_text("✅ Пост удалён.", reply_markup=back_kb("menu:posts"))
    await callback.answer()
