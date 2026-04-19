from __future__ import annotations

import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.chats_kb import (
    chat_add_method_kb,
    chat_picker_reply_kb,
    remove_reply_kb,
)
from bot.keyboards.utils import back_kb, cancel_kb, esc, remember_prompt, reprompt
from bot.states.fsm import ChatAdd, ChatImport
from db.models import User
from db.repositories.chat_repo import ChatRepository
from db.repositories.session_repo import SessionRepository
from db.session import async_session_factory
from services.chat_resolver import ResolvedChat, ResolverError, from_forwarded_chat, resolve
from services.session_client import borrow_client

router = Router()


def _chats_list_kb(chats: list, page: int = 0):  # type: ignore[return]
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    from bot.keyboards.utils import back_button, paginate

    sliced, page_kb = paginate(chats, page, page_size=10, callback_prefix="chats:page")
    rows = []
    for c in sliced:
        rows.append([
            InlineKeyboardButton(text=f"💬 {c.title}", callback_data=f"chat:view:{c.id}"),
        ])
    if page_kb:
        rows.extend(page_kb.inline_keyboard)
    rows.append([
        InlineKeyboardButton(text="➕ Добавить", callback_data="chat:add"),
        InlineKeyboardButton(text="📋 Импорт", callback_data="chat:import"),
    ])
    rows.append([back_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "menu:chats")
async def cb_chats_list(callback: CallbackQuery, db_user: User) -> None:
    if not callback.message:
        await callback.answer()
        return
    async with async_session_factory() as session:
        repo = ChatRepository(session)
        chats = await repo.get_by_user(db_user.tg_id)
    text = f"💬 <b>Чаты рассылки</b> ({len(chats)})\n\n"
    text += (
        "Это глобальный список. При создании кампании выбираешь из него."
        if chats
        else "Список пуст. Добавь первый чат через ➕."
    )
    await callback.message.edit_text(text, reply_markup=_chats_list_kb(chats))
    await callback.answer()


@router.callback_query(F.data.startswith("chats:page:"))
async def cb_chats_page(callback: CallbackQuery, db_user: User) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    page = int(callback.data.split(":", 2)[2])
    async with async_session_factory() as session:
        repo = ChatRepository(session)
        chats = await repo.get_by_user(db_user.tg_id)
    await callback.message.edit_reply_markup(reply_markup=_chats_list_kb(chats, page=page))
    await callback.answer()


# ── Add chat: method picker ───────────────────────────────────────────────────

@router.callback_query(F.data == "chat:add")
async def cb_chat_add(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return
    await callback.message.edit_text(
        "➕ <b>Добавить чат</b>\n\n"
        "Выбери, как добавить:\n"
        "• <b>📲 Выбрать из своих чатов</b> — открывается Telegram-пикер.\n"
        "• <b>📤 Переслать сообщение</b> — для приватных групп.\n"
        "• <b>🔗 Ссылка / @username / ID</b> — для публичных каналов.",
        reply_markup=chat_add_method_kb(),
    )
    await state.set_state(ChatAdd.waiting_method)
    await callback.answer()


# ── Add chat: native chat picker (Bot API 7.0+) ───────────────────────────────

@router.callback_query(F.data == "chat:add:picker", ChatAdd.waiting_method)
async def cb_chat_add_picker(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return
    await callback.message.answer(
        "📲 Выбери чат через нативный пикер Telegram ниже.\n\n"
        "Бот получит chat_id автоматически.",
        reply_markup=chat_picker_reply_kb(),
    )
    await state.set_state(ChatAdd.waiting_picker)
    await callback.answer()


@router.message(ChatAdd.waiting_picker, F.chat_shared)
async def fsm_chat_shared(message: Message, state: FSMContext, db_user: User) -> None:
    shared = message.chat_shared
    if not shared:
        await message.answer("Не получил chat_shared.", reply_markup=remove_reply_kb())
        return
    chat_id = shared.chat_id
    title = shared.title or str(chat_id)
    username = shared.username
    await _save_chat(
        message,
        state,
        db_user,
        ResolvedChat(chat_id=chat_id, title=title, username=username),
        verify_via_session=True,
    )


@router.message(ChatAdd.waiting_picker, F.text == "❌ Отмена")
async def fsm_picker_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=remove_reply_kb())
    await message.answer("💬 <b>Чаты рассылки</b>", reply_markup=back_kb("menu:chats"))


# ── Add chat: forwarded message ───────────────────────────────────────────────

@router.callback_query(F.data == "chat:add:forward", ChatAdd.waiting_method)
async def cb_chat_add_forward(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return
    sent = await callback.message.edit_text(
        "📤 <b>Перешли сообщение</b>\n\n"
        "Перешли любое сообщение из канала или группы, которую хочешь добавить.\n"
        "Если у автора скрыт источник — используй другой способ.",
        reply_markup=cancel_kb("menu:chats"),
    )
    await remember_prompt(state, sent)
    await state.set_state(ChatAdd.waiting_forward)
    await callback.answer()


@router.message(ChatAdd.waiting_forward)
async def fsm_chat_add_forward(message: Message, state: FSMContext, db_user: User) -> None:
    try:
        resolved = from_forwarded_chat(message.forward_from_chat)
    except ResolverError as e:
        await reprompt(message, state, f"⚠️ {e}", reply_markup=cancel_kb("menu:chats"))
        return
    await _save_chat(message, state, db_user, resolved, verify_via_session=False)


# ── Add chat: link / @username / numeric ID ───────────────────────────────────

@router.callback_query(F.data == "chat:add:link", ChatAdd.waiting_method)
async def cb_chat_add_link(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return
    sent = await callback.message.edit_text(
        "🔗 <b>Вставь ссылку, @username или числовой ID</b>\n\n"
        "Примеры:\n"
        "• <code>@channel</code>\n"
        "• <code>https://t.me/channel</code>\n"
        "• <code>-1001234567890</code>",
        reply_markup=cancel_kb("menu:chats"),
    )
    await remember_prompt(state, sent)
    await state.set_state(ChatAdd.waiting_link)
    await callback.answer()


@router.message(ChatAdd.waiting_link)
async def fsm_chat_add_link(message: Message, state: FSMContext, db_user: User) -> None:
    text = (message.text or "").strip()
    async with async_session_factory() as session:
        s_repo = SessionRepository(session)
        active_sessions = [s for s in await s_repo.get_by_user(db_user.tg_id) if s.is_active]
    if not active_sessions:
        await reprompt(
            message,
            state,
            "⚠️ Нужна хотя бы одна активная сессия в разделе «Сессии».",
            reply_markup=back_kb("menu:chats"),
        )
        return

    status_msg = await message.answer("⏳ Ищу чат...")
    async with borrow_client(active_sessions[0]) as client:
        if client is None:
            await status_msg.edit_text(
                "⚠️ Сессия не авторизована. Переподключи её в разделе «Сессии».",
                reply_markup=back_kb("menu:chats"),
            )
            return
        try:
            resolved = await resolve(client, text)
        except ResolverError as e:
            await status_msg.delete()
            await reprompt(message, state, f"⚠️ {e}", reply_markup=cancel_kb("menu:chats"))
            return

    await status_msg.delete()
    await _save_chat(message, state, db_user, resolved, verify_via_session=False)


# ── Save resolved chat ────────────────────────────────────────────────────────

async def _save_chat(
    message: Message,
    state: FSMContext,
    db_user: User,
    resolved: ResolvedChat,
    *,
    verify_via_session: bool,
) -> None:
    """Persist a resolved chat. If verify_via_session, ping it via an active session
    first to confirm at least one of the user's sessions can see it."""
    if verify_via_session:
        async with async_session_factory() as session:
            s_repo = SessionRepository(session)
            active_sessions = [s for s in await s_repo.get_by_user(db_user.tg_id) if s.is_active]
        if active_sessions:
            async with borrow_client(active_sessions[0]) as client:
                if client is not None:
                    try:
                        await client.get_entity(resolved.chat_id)
                    except Exception:
                        await message.answer(
                            f"⚠️ Сессия не видит чат «{esc(resolved.title)}». "
                            "Убедись, что аккаунт сессии состоит в нём — иначе рассылка не пойдёт.",
                            reply_markup=remove_reply_kb(),
                        )

    async with async_session_factory() as session:
        async with session.begin():
            repo = ChatRepository(session)
            existing = await repo.find_by_chat_id(db_user.tg_id, resolved.chat_id)
            if existing:
                await state.clear()
                await message.answer(
                    f"⚠️ Чат <b>{esc(resolved.title)}</b> уже добавлен.",
                    reply_markup=remove_reply_kb(),
                )
                await message.answer("💬 <b>Чаты рассылки</b>", reply_markup=back_kb("menu:chats"))
                return
            await repo.create(
                user_id=db_user.tg_id,
                chat_id=resolved.chat_id,
                title=resolved.title,
                username=resolved.username,
            )

    await state.clear()
    await message.answer(
        f"✅ Чат <b>{esc(resolved.title)}</b> добавлен!",
        reply_markup=remove_reply_kb(),
    )
    await message.answer("💬 <b>Чаты рассылки</b>", reply_markup=back_kb("menu:chats"))


# ── Import chats from text list ───────────────────────────────────────────────

@router.callback_query(F.data == "chat:import")
async def cb_chat_import(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return
    sent = await callback.message.edit_text(
        "📋 <b>Импорт чатов</b>\n\n"
        "Отправь список — каждый чат с новой строки. Поддерживаются "
        "<code>@username</code>, <code>t.me/username</code> и <code>-100…</code>.",
        reply_markup=cancel_kb("menu:chats"),
    )
    await remember_prompt(state, sent)
    await state.set_state(ChatImport.waiting_list)
    await callback.answer()


@router.message(ChatImport.waiting_list)
async def fsm_chat_import(message: Message, state: FSMContext, db_user: User) -> None:
    text = (message.text or "").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        await reprompt(message, state, "Список пуст. Попробуй ещё раз:", reply_markup=cancel_kb("menu:chats"))
        return

    async with async_session_factory() as session:
        s_repo = SessionRepository(session)
        active_sessions = [s for s in await s_repo.get_by_user(db_user.tg_id) if s.is_active]

    if not active_sessions:
        await reprompt(
            message, state,
            "⚠️ Нужна хотя бы одна активная сессия в разделе «Сессии».",
            reply_markup=back_kb("menu:chats"),
        )
        return

    status_msg = await message.answer(f"⏳ Обрабатываю {len(lines)} чатов...")
    resolved: list[dict] = []
    errors: list[str] = []

    async with borrow_client(active_sessions[0]) as client:
        if client is None:
            await status_msg.edit_text(
                "⚠️ Сессия не авторизована.",
                reply_markup=back_kb("menu:chats"),
            )
            return
        for line in lines:
            try:
                r = await resolve(client, line)
                resolved.append({
                    "chat_id": r.chat_id,
                    "title": r.title,
                    "username": r.username,
                })
            except ResolverError:
                errors.append(line)

    async with async_session_factory() as session:
        async with session.begin():
            repo = ChatRepository(session)
            created = await repo.bulk_create(db_user.tg_id, resolved)

    await state.clear()
    result_text = f"✅ Добавлено чатов: <b>{len(created)}</b>"
    if errors:
        sample = ", ".join(esc(e) for e in errors[:5])
        result_text += f"\n❌ Не удалось ({len(errors)}): {sample}"
        if len(errors) > 5:
            result_text += f" и ещё {len(errors) - 5}"
    await status_msg.edit_text(result_text, reply_markup=back_kb("menu:chats"))


# ── View / delete chat ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("chat:view:"))
async def cb_chat_view(callback: CallbackQuery) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    chat_id = callback.data.split(":", 2)[2]
    async with async_session_factory() as session:
        repo = ChatRepository(session)
        chat = await repo.get(uuid.UUID(chat_id))
    if not chat:
        await callback.answer("Чат не найден", show_alert=True)
        return
    username_line = f"@{esc(chat.username)}" if chat.username else "—"
    text = (
        f"💬 <b>{esc(chat.title)}</b>\n\n"
        f"ID: <code>{chat.chat_id}</code>\n"
        f"Username: {username_line}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"chat:delete:confirm_ask:{chat_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:chats")],
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("chat:delete:confirm_ask:"))
async def cb_chat_delete_ask(callback: CallbackQuery) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    chat_id = callback.data.split(":", 3)[3]
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Удалить", callback_data=f"chat:delete:{chat_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"chat:view:{chat_id}"),
        ]
    ])
    await callback.message.edit_text(
        "🗑 <b>Удалить чат из списка?</b>\n\nОн будет убран из всех кампаний.",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("chat:delete:") & ~F.data.startswith("chat:delete:confirm_ask:"))
async def cb_chat_delete(callback: CallbackQuery) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    chat_id = callback.data.split(":", 2)[2]
    async with async_session_factory() as session:
        async with session.begin():
            repo = ChatRepository(session)
            await repo.delete(uuid.UUID(chat_id))
    await callback.message.edit_text("✅ Чат удалён.", reply_markup=back_kb("menu:chats"))
    await callback.answer()
