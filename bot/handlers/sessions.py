from __future__ import annotations

import asyncio
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.keyboards.sessions_kb import (
    session_add_method_kb,
    session_confirm_delete_kb,
    session_view_kb,
    sessions_list_kb,
)
from bot.keyboards.utils import back_kb
from bot.states.fsm import SessionAddPhone, SessionAddQR
from db.models import User
from db.repositories.session_repo import SessionRepository
from db.session import async_session_factory
from services.session_auth import PhoneLoginSession, QRLoginSession

router = Router()

# In-memory store for active auth sessions (keyed by user tg_id)
_qr_sessions: dict[int, QRLoginSession] = {}
_phone_sessions: dict[int, PhoneLoginSession] = {}


# ── Sessions list ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:sessions")
async def cb_sessions_list(callback: CallbackQuery, db_user: User) -> None:
    assert callback.message
    async with async_session_factory() as session:
        repo = SessionRepository(session)
        sessions = await repo.get_by_user(db_user.tg_id)
    count = len(sessions)
    text = f"📱 <b>Сессии</b> ({count})\n\nВыбери сессию или добавь новую:"
    await callback.message.edit_text(text, reply_markup=sessions_list_kb(sessions))
    await callback.answer()


# ── View session ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("session:view:"))
async def cb_session_view(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    session_id = callback.data.split(":", 2)[2]
    import uuid
    async with async_session_factory() as session:
        repo = SessionRepository(session)
        tg_session = await repo.get(uuid.UUID(session_id))
    if not tg_session:
        await callback.answer("Сессия не найдена", show_alert=True)
        return
    premium = "💎 Premium" if tg_session.has_premium else "Нет"
    text = (
        f"📱 <b>{tg_session.name}</b>\n\n"
        f"👤 Аккаунт: {tg_session.account_name or '—'}\n"
        f"🆔 @{tg_session.account_username or '—'}\n"
        f"📞 {tg_session.phone or '—'}\n"
        f"⭐ Premium: {premium}\n"
        f"🕐 Добавлена: {tg_session.created_at.strftime('%d.%m.%Y %H:%M')}"
    )
    await callback.message.edit_text(text, reply_markup=session_view_kb(session_id))
    await callback.answer()


# ── Add session — method selection ────────────────────────────────────────────

@router.callback_query(F.data == "session:add")
async def cb_session_add(callback: CallbackQuery) -> None:
    assert callback.message
    await callback.message.edit_text(
        "➕ <b>Добавить сессию</b>\n\nВыбери способ авторизации:",
        reply_markup=session_add_method_kb(),
    )
    await callback.answer()


# ── QR Login flow ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "session:add:qr")
async def cb_session_add_qr(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message
    await callback.message.edit_text(
        "📷 <b>QR-авторизация</b>\n\nВведи название для этой сессии (например: «Основной аккаунт»):"
    )
    await state.set_state(SessionAddQR.waiting_name)
    await callback.answer()


@router.message(SessionAddQR.waiting_name)
async def fsm_qr_name(message: Message, state: FSMContext, db_user: User) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название не может быть пустым. Введи ещё раз:")
        return
    await state.update_data(session_name=name)

    status_msg = await message.answer("⏳ Генерирую QR-код...")
    auth = QRLoginSession()
    _qr_sessions[db_user.tg_id] = auth

    try:
        qr_bytes = await auth.start()
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {e}")
        await state.clear()
        return

    from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
    photo = BufferedInputFile(qr_bytes, filename="qr.png")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить QR", callback_data="session:qr:refresh")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="session:qr:cancel")],
        ]
    )
    await status_msg.delete()
    await message.answer_photo(
        photo,
        caption=(
            "📷 <b>Отсканируй QR-код</b>\n\n"
            "Открой Telegram → <b>Настройки</b> → <b>Устройства</b> → <b>Подключить устройство</b>\n\n"
            "QR-код действителен 1 минуту."
        ),
        reply_markup=kb,
    )
    await state.set_state(SessionAddQR.waiting_scan)

    # Background task: wait for scan
    asyncio.create_task(_wait_for_qr_scan(message.from_user.id, message.chat.id, state))  # type: ignore[union-attr]


async def _wait_for_qr_scan(user_id: int, chat_id: int, state: FSMContext) -> None:
    from bot.core.bot import bot
    auth = _qr_sessions.get(user_id)
    if not auth:
        return
    result = await auth.wait_for_scan(timeout=60.0)
    if result == "success":
        auth_result = await auth.finalize()
        await _save_session(user_id, chat_id, state, auth_result)
    elif result == "password_needed":
        await bot.send_message(chat_id, "🔐 Введи пароль двухфакторной аутентификации:")
        await state.set_state(SessionAddQR.waiting_2fa)
    else:
        await bot.send_message(chat_id, "⏰ QR-код истёк. Нажми «Обновить QR» или начни заново.")


@router.callback_query(F.data == "session:qr:refresh", SessionAddQR.waiting_scan)
async def cb_qr_refresh(callback: CallbackQuery, db_user: User) -> None:
    assert callback.message
    auth = _qr_sessions.get(db_user.tg_id)
    if not auth:
        await callback.answer("Сессия устарела. Начни заново.", show_alert=True)
        return
    qr_bytes = await auth.refresh_qr()
    photo = BufferedInputFile(qr_bytes, filename="qr.png")
    await callback.message.delete()
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить QR", callback_data="session:qr:refresh")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="session:qr:cancel")],
        ]
    )
    assert callback.bot
    await callback.bot.send_photo(
        callback.from_user.id,
        photo,
        caption="🔄 QR обновлён. Отсканируй снова.",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(F.data == "session:qr:cancel")
async def cb_qr_cancel(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    assert callback.message
    auth = _qr_sessions.pop(db_user.tg_id, None)
    if auth:
        await auth.cancel()
    await state.clear()
    await callback.message.edit_caption("❌ Авторизация отменена.")
    await callback.answer()


@router.message(SessionAddQR.waiting_2fa)
async def fsm_qr_2fa(message: Message, state: FSMContext, db_user: User) -> None:
    password = (message.text or "").strip()
    auth = _qr_sessions.get(db_user.tg_id)
    if not auth:
        await message.answer("❌ Сессия устарела. Начни заново.", reply_markup=back_kb("menu:sessions"))
        await state.clear()
        return
    auth_result = await auth.submit_password(password)
    _qr_sessions.pop(db_user.tg_id, None)
    await _save_session(db_user.tg_id, message.chat.id, state, auth_result, message)


# ── Phone Login flow ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "session:add:phone")
async def cb_session_add_phone(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message
    await callback.message.edit_text(
        "📞 <b>Авторизация по номеру</b>\n\nВведи название для этой сессии:"
    )
    await state.set_state(SessionAddPhone.waiting_name)
    await callback.answer()


@router.message(SessionAddPhone.waiting_name)
async def fsm_phone_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название не может быть пустым:")
        return
    await state.update_data(session_name=name)
    await message.answer("📞 Введи номер телефона в формате <code>+7XXXXXXXXXX</code>:")
    await state.set_state(SessionAddPhone.waiting_phone)


@router.message(SessionAddPhone.waiting_phone)
async def fsm_phone_number(message: Message, state: FSMContext, db_user: User) -> None:
    phone = (message.text or "").strip()
    auth = PhoneLoginSession()
    _phone_sessions[db_user.tg_id] = auth

    status = await message.answer("⏳ Отправляю код...")
    success, error = await auth.send_code(phone)
    if not success:
        _phone_sessions.pop(db_user.tg_id, None)
        await status.edit_text(f"❌ Ошибка: {error}")
        return
    await status.edit_text(
        "📨 Код отправлен в Telegram.\n\n"
        "Введи код (цифры без пробелов, например <code>12345</code>):"
    )
    await state.set_state(SessionAddPhone.waiting_code)


@router.message(SessionAddPhone.waiting_code)
async def fsm_phone_code(message: Message, state: FSMContext, db_user: User) -> None:
    code = (message.text or "").strip()
    auth = _phone_sessions.get(db_user.tg_id)
    if not auth:
        await message.answer("❌ Сессия устарела. Начни заново.", reply_markup=back_kb("menu:sessions"))
        await state.clear()
        return
    result, error = await auth.submit_code(code)
    if result == "success":
        auth_result = await auth.finalize()
        _phone_sessions.pop(db_user.tg_id, None)
        await _save_session(db_user.tg_id, message.chat.id, state, auth_result, message)
    elif result == "password_needed":
        await message.answer("🔐 Введи пароль двухфакторной аутентификации:")
        await state.set_state(SessionAddPhone.waiting_2fa)
    else:
        await message.answer(f"❌ {error}")


@router.message(SessionAddPhone.waiting_2fa)
async def fsm_phone_2fa(message: Message, state: FSMContext, db_user: User) -> None:
    password = (message.text or "").strip()
    auth = _phone_sessions.get(db_user.tg_id)
    if not auth:
        await message.answer("❌ Сессия устарела. Начни заново.")
        await state.clear()
        return
    success, error = await auth.submit_password(password)
    if not success:
        await message.answer(f"❌ Неверный пароль: {error}\nПопробуй ещё раз:")
        return
    auth_result = await auth.finalize()
    _phone_sessions.pop(db_user.tg_id, None)
    await _save_session(db_user.tg_id, message.chat.id, state, auth_result, message)


# ── Delete session ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("session:delete:") & ~F.data.startswith("session:delete:confirm:"))
async def cb_session_delete(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    session_id = callback.data.split(":", 2)[2]
    await callback.message.edit_text(
        "🗑 <b>Удалить сессию?</b>\n\nЭто действие необратимо. Активные кампании с этой сессией будут остановлены.",
        reply_markup=session_confirm_delete_kb(session_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("session:delete:confirm:"))
async def cb_session_delete_confirm(callback: CallbackQuery, db_user: User) -> None:
    assert callback.message and callback.data
    session_id = callback.data.split(":", 3)[3]
    import uuid
    async with async_session_factory() as session:
        async with session.begin():
            repo = SessionRepository(session)
            await repo.delete(uuid.UUID(session_id))
    await callback.message.edit_text("✅ Сессия удалена.", reply_markup=back_kb("menu:sessions"))
    await callback.answer()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _save_session(
    user_id: int,
    chat_id: int,
    state: FSMContext,
    auth_result: Any,
    message: Message | None = None,
) -> None:
    from bot.core.bot import bot

    data = await state.get_data()
    session_name = data.get("session_name", "Без названия")
    await state.clear()

    if not auth_result.success:
        text = f"❌ Ошибка авторизации: {auth_result.error}"
        if message:
            await message.answer(text, reply_markup=back_kb("menu:sessions"))
        else:
            await bot.send_message(chat_id, text, reply_markup=back_kb("menu:sessions"))
        return

    async with async_session_factory() as db_session:
        async with db_session.begin():
            repo = SessionRepository(db_session)
            tg_session = await repo.create(
                user_id=user_id,
                name=session_name,
                encrypted_session=auth_result.encrypted_session,
                phone=auth_result.phone,
                has_premium=auth_result.has_premium,
                account_name=auth_result.account_name,
                account_username=auth_result.account_username,
            )

    premium = "💎 Premium" if auth_result.has_premium else "нет"
    text = (
        f"✅ <b>Сессия добавлена!</b>\n\n"
        f"📱 {session_name}\n"
        f"👤 {auth_result.account_name or '—'}\n"
        f"⭐ Premium: {premium}"
    )
    if message:
        await message.answer(text, reply_markup=back_kb("menu:sessions"))
    else:
        await bot.send_message(chat_id, text, reply_markup=back_kb("menu:sessions"))
