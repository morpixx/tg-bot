from __future__ import annotations

import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.utils import back_kb
from bot.states.fsm import ChatAdd, ChatImport
from db.models import User
from db.repositories.chat_repo import ChatRepository
from db.session import async_session_factory

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
    assert callback.message
    async with async_session_factory() as session:
        repo = ChatRepository(session)
        chats = await repo.get_by_user(db_user.tg_id)
    await callback.message.edit_text(
        f"💬 <b>Чаты рассылки</b> ({len(chats)})\n\nЭто глобальный список. При создании кампании выбираешь из него:",
        reply_markup=_chats_list_kb(chats),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("chats:page:"))
async def cb_chats_page(callback: CallbackQuery, db_user: User) -> None:
    assert callback.message and callback.data
    page = int(callback.data.split(":", 2)[2])
    async with async_session_factory() as session:
        repo = ChatRepository(session)
        chats = await repo.get_by_user(db_user.tg_id)
    await callback.message.edit_reply_markup(reply_markup=_chats_list_kb(chats, page=page))
    await callback.answer()


# ── Add single chat ───────────────────────────────────────────────────────────

@router.callback_query(F.data == "chat:add")
async def cb_chat_add(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message
    await callback.message.edit_text(
        "➕ <b>Добавить чат</b>\n\n"
        "Отправь username канала/группы (например <code>@mychannel</code>) "
        "или числовой ID (например <code>-1001234567890</code>):"
    )
    await state.set_state(ChatAdd.waiting_chat)
    await callback.answer()


@router.message(ChatAdd.waiting_chat)
async def fsm_chat_add(message: Message, state: FSMContext, db_user: User) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Введи username или ID чата:")
        return

    # Resolve chat info via bot
    try:
        chat = await message.bot.get_chat(text)  # type: ignore[union-attr]
    except Exception as e:
        await message.answer(f"❌ Не удалось найти чат: {e}\n\nПроверь username/ID и доступность бота в чате.")
        return

    async with async_session_factory() as session:
        async with session.begin():
            repo = ChatRepository(session)
            existing = await repo.find_by_chat_id(db_user.tg_id, chat.id)
            if existing:
                await message.answer(f"⚠️ Чат <b>{chat.title}</b> уже добавлен.", reply_markup=back_kb("menu:chats"))
                await state.clear()
                return
            await repo.create(
                user_id=db_user.tg_id,
                chat_id=chat.id,
                title=chat.title or str(chat.id),
                username=chat.username,
            )

    await state.clear()
    await message.answer(
        f"✅ Чат <b>{chat.title}</b> добавлен!",
        reply_markup=back_kb("menu:chats"),
    )


# ── Import chats from text list ───────────────────────────────────────────────

@router.callback_query(F.data == "chat:import")
async def cb_chat_import(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message
    await callback.message.edit_text(
        "📋 <b>Импорт чатов</b>\n\n"
        "Отправь список чатов — каждый с новой строки.\n"
        "Поддерживаются username <code>@channel</code> и ID <code>-1001234567890</code>:"
    )
    await state.set_state(ChatImport.waiting_list)
    await callback.answer()


@router.message(ChatImport.waiting_list)
async def fsm_chat_import(message: Message, state: FSMContext, db_user: User) -> None:
    text = (message.text or "").strip()
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        await message.answer("Список пуст. Попробуй ещё раз:")
        return

    status_msg = await message.answer(f"⏳ Обрабатываю {len(lines)} чатов...")
    resolved: list[dict] = []
    errors: list[str] = []

    for line in lines:
        try:
            chat = await message.bot.get_chat(line)  # type: ignore[union-attr]
            resolved.append({
                "chat_id": chat.id,
                "title": chat.title or str(chat.id),
                "username": chat.username,
            })
        except Exception:
            errors.append(line)

    async with async_session_factory() as session:
        async with session.begin():
            repo = ChatRepository(session)
            created = await repo.bulk_create(db_user.tg_id, resolved)

    await state.clear()
    result_text = f"✅ Добавлено чатов: <b>{len(created)}</b>"
    if errors:
        result_text += f"\n❌ Не удалось найти ({len(errors)}): {', '.join(errors[:5])}"
        if len(errors) > 5:
            result_text += f" и ещё {len(errors) - 5}"
    await status_msg.edit_text(result_text, reply_markup=back_kb("menu:chats"))


# ── View / delete chat ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("chat:view:"))
async def cb_chat_view(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    chat_id = callback.data.split(":", 2)[2]
    async with async_session_factory() as session:
        repo = ChatRepository(session)
        chat = await repo.get(uuid.UUID(chat_id))
    if not chat:
        await callback.answer("Чат не найден", show_alert=True)
        return
    username_line = f"@{chat.username}" if chat.username else "—"
    text = (
        f"💬 <b>{chat.title}</b>\n\n"
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
    assert callback.message and callback.data
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
    assert callback.message and callback.data
    chat_id = callback.data.split(":", 2)[2]
    async with async_session_factory() as session:
        async with session.begin():
            repo = ChatRepository(session)
            await repo.delete(uuid.UUID(chat_id))
    await callback.message.edit_text("✅ Чат удалён.", reply_markup=back_kb("menu:chats"))
    await callback.answer()
