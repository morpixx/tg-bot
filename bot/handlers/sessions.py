from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.keyboards.sessions_kb import (
    phone_retry_kb,
    qr_auth_kb,
    session_add_method_kb,
    session_confirm_delete_kb,
    session_view_kb,
    sessions_list_kb,
)
from bot.keyboards.utils import back_kb
from bot.states.fsm import SessionAddPhone, SessionAddQR, SessionRename
from db.models import User
from db.repositories.session_repo import SessionRepository
from db.session import async_session_factory
from services.session_auth import AuthResult, PhoneLoginSession, QRLoginSession
from worker.session_pool import SessionPool

router = Router()
log = structlog.get_logger()

# In-memory store for active auth sessions (keyed by user tg_id)
_qr_sessions: dict[int, QRLoginSession] = {}
_qr_tasks: dict[int, asyncio.Task] = {}  # type: ignore[type-arg]
_phone_sessions: dict[int, PhoneLoginSession] = {}


def _default_session_name(auth_result: AuthResult) -> str:
    """Derive a human-readable default name from the auth result."""
    if auth_result.account_name:
        return auth_result.account_name
    if auth_result.account_username:
        return f"@{auth_result.account_username}"
    if auth_result.phone:
        return auth_result.phone
    return "Новая сессия"


def _render_session_view(tg_session) -> str:  # type: ignore[no-untyped-def]
    premium = "💎 Premium" if tg_session.has_premium else "нет"
    status = "🟢 Активна" if tg_session.is_active else "🔴 Отключена"
    return (
        f"📱 <b>{tg_session.name}</b>\n\n"
        f"🔌 Статус: {status}\n"
        f"👤 Аккаунт: {tg_session.account_name or '—'}\n"
        f"🆔 @{tg_session.account_username or '—'}\n"
        f"📞 {tg_session.phone or '—'}\n"
        f"⭐ Premium: {premium}\n"
        f"🕐 Добавлена: {tg_session.created_at.strftime('%d.%m.%Y %H:%M')}"
    )


# ── Sessions list ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:sessions")
async def cb_sessions_list(callback: CallbackQuery, db_user: User) -> None:
    assert callback.message
    async with async_session_factory() as session:
        repo = SessionRepository(session)
        sessions = await repo.get_all_by_user(db_user.tg_id)
    active = sum(1 for s in sessions if s.is_active)
    total = len(sessions)
    text = f"📱 <b>Сессии</b> ({active}/{total} активных)\n\nВыбери сессию или добавь новую:"
    try:
        await callback.message.edit_text(text, reply_markup=sessions_list_kb(sessions))
    except Exception:
        await callback.message.answer(text, reply_markup=sessions_list_kb(sessions))
    await callback.answer()


# ── View session ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("session:view:"))
async def cb_session_view(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    session_id = callback.data.split(":", 2)[2]
    async with async_session_factory() as session:
        repo = SessionRepository(session)
        tg_session = await repo.get(uuid.UUID(session_id))
    if not tg_session:
        await callback.answer("Сессия не найдена", show_alert=True)
        return
    try:
        await callback.message.edit_text(
            _render_session_view(tg_session), reply_markup=session_view_kb(session_id)
        )
    except Exception:
        await callback.message.answer(
            _render_session_view(tg_session), reply_markup=session_view_kb(session_id)
        )
    await callback.answer()


# ── Rename session ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("session:rename:"))
async def cb_session_rename(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message and callback.data
    session_id = callback.data.split(":", 2)[2]
    await state.clear()
    await state.update_data(rename_session_id=session_id)
    await callback.message.answer(
        "✏️ Введи новое название для сессии:",
        reply_markup=back_kb(f"session:view:{session_id}"),
    )
    await state.set_state(SessionRename.waiting_name)
    await callback.answer()


@router.message(SessionRename.waiting_name)
async def fsm_rename(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название не может быть пустым. Введи ещё раз:")
        return
    if len(name) > 64:
        await message.answer("Слишком длинное (макс 64 символа). Введи короче:")
        return
    data = await state.get_data()
    session_id = data.get("rename_session_id")
    await state.clear()
    if not session_id:
        await message.answer("❌ Сессия не найдена.", reply_markup=back_kb("menu:sessions"))
        return
    async with async_session_factory() as db_session:
        async with db_session.begin():
            repo = SessionRepository(db_session)
            await repo.update(uuid.UUID(session_id), name=name)
    async with async_session_factory() as db_session:
        repo = SessionRepository(db_session)
        tg_session = await repo.get(uuid.UUID(session_id))
    assert tg_session
    await message.answer(
        f"✅ Переименовано.\n\n{_render_session_view(tg_session)}",
        reply_markup=session_view_kb(session_id),
    )


# ── Add session — method selection ────────────────────────────────────────────

@router.callback_query(F.data == "session:add")
async def cb_session_add(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message
    await state.clear()
    await callback.message.edit_text(
        "➕ <b>Добавить сессию</b>\n\nВыбери способ авторизации:",
        reply_markup=session_add_method_kb(),
    )
    await callback.answer()


# ── QR Login flow ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "session:add:qr")
async def cb_session_add_qr(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    assert callback.message
    await state.clear()

    status_msg = await callback.message.answer("⏳ Генерирую QR-код...")
    auth = QRLoginSession()
    _qr_sessions[db_user.tg_id] = auth

    try:
        qr_bytes = await auth.start()
    except Exception as e:
        log.error("QR start failed", user_id=db_user.tg_id, error=str(e))
        _qr_sessions.pop(db_user.tg_id, None)
        await status_msg.edit_text(f"❌ Ошибка: {e}", reply_markup=back_kb("menu:sessions"))
        return

    login_url = auth.login_url()
    photo = BufferedInputFile(qr_bytes, filename="qr.png")
    await status_msg.delete()
    await callback.message.answer_photo(
        photo,
        caption=(
            "📷 <b>Авторизация сессии</b>\n\n"
            "Два способа:\n"
            "• <b>Отсканируй QR-код</b> камерой Telegram (Настройки → Устройства → Подключить устройство)\n"
            "• <b>Или нажми кнопку ниже</b> на том аккаунте, который хочешь добавить — "
            "ссылку можно переслать куда угодно\n\n"
            "⏳ Ссылка/QR действительны 1 минуту."
        ),
        reply_markup=qr_auth_kb(login_url),
    )
    await state.set_state(SessionAddQR.waiting_scan)
    await callback.answer()

    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    task = asyncio.create_task(_wait_for_qr_scan(user_id, chat_id, state))
    _qr_tasks[user_id] = task


async def _wait_for_qr_scan(user_id: int, chat_id: int, state: FSMContext) -> None:
    from bot.core.bot import bot
    auth = _qr_sessions.get(user_id)
    if not auth:
        log.warning("QR waiter started without auth", user_id=user_id)
        return
    try:
        result = await auth.wait_for_scan(timeout=60.0)
    except asyncio.CancelledError:
        return
    except Exception as e:
        log.error("QR wait failed", user_id=user_id, error=str(e))
        _qr_sessions.pop(user_id, None)
        _qr_tasks.pop(user_id, None)
        await state.clear()
        try:
            await bot.send_message(
                chat_id,
                f"❌ Ошибка при ожидании QR: {e}",
                reply_markup=back_kb("menu:sessions"),
            )
        except Exception:
            pass
        return

    log.info("QR wait returned", user_id=user_id, result=result)

    if result == "success":
        _qr_sessions.pop(user_id, None)
        _qr_tasks.pop(user_id, None)
        try:
            await bot.send_message(chat_id, "✅ Авторизовано! Сохраняю сессию...")
        except Exception:
            pass
        try:
            auth_result = await auth.finalize()
        except Exception as e:
            log.exception("QR finalize crashed", user_id=user_id)
            await state.clear()
            await bot.send_message(
                chat_id,
                f"❌ Не удалось завершить авторизацию: {e}",
                reply_markup=back_kb("menu:sessions"),
            )
            return
        await _save_session(user_id, chat_id, state, auth_result)
    elif result == "password_needed":
        await bot.send_message(chat_id, "🔐 Введи пароль двухфакторной аутентификации:")
        await state.set_state(SessionAddQR.waiting_2fa)
    else:
        await bot.send_message(chat_id, "⏰ QR-код истёк. Нажми «Обновить QR» или начни заново.")


@router.callback_query(F.data == "session:qr:refresh", SessionAddQR.waiting_scan)
async def cb_qr_refresh(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    assert callback.message
    user_id = db_user.tg_id
    chat_id = callback.message.chat.id

    auth = _qr_sessions.get(user_id)
    if not auth:
        await callback.answer("Сессия устарела. Начни заново.", show_alert=True)
        return

    try:
        qr_bytes = await auth.refresh_qr()
    except Exception as e:
        await callback.answer(f"❌ Ошибка обновления: {e}", show_alert=True)
        return

    old_task = _qr_tasks.pop(user_id, None)
    if old_task and not old_task.done():
        old_task.cancel()

    login_url = auth.login_url()
    photo = BufferedInputFile(qr_bytes, filename="qr.png")
    try:
        await callback.message.delete()
    except Exception:
        pass
    assert callback.bot
    await callback.bot.send_photo(
        callback.from_user.id,
        photo,
        caption="🔄 QR обновлён. Отсканируй или нажми кнопку.",
        reply_markup=qr_auth_kb(login_url),
    )

    task = asyncio.create_task(_wait_for_qr_scan(user_id, chat_id, state))
    _qr_tasks[user_id] = task

    await callback.answer()


@router.callback_query(F.data == "session:qr:cancel")
async def cb_qr_cancel(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    assert callback.message
    user_id = db_user.tg_id
    task = _qr_tasks.pop(user_id, None)
    if task and not task.done():
        task.cancel()
    auth = _qr_sessions.pop(user_id, None)
    if auth:
        await auth.cancel()
    await state.clear()
    try:
        await callback.message.edit_caption(caption="❌ Авторизация отменена.")
    except Exception:
        await callback.message.answer("❌ Авторизация отменена.")
    await callback.answer()


@router.message(SessionAddQR.waiting_2fa)
async def fsm_qr_2fa(message: Message, state: FSMContext, db_user: User) -> None:
    password = (message.text or "").strip()
    auth = _qr_sessions.get(db_user.tg_id)
    if not auth:
        await message.answer("❌ Сессия устарела. Начни заново.", reply_markup=back_kb("menu:sessions"))
        await state.clear()
        return
    try:
        auth_result = await auth.submit_password(password)
    except Exception as e:
        log.exception("QR 2FA submit crashed", user_id=db_user.tg_id)
        await message.answer(f"❌ Ошибка при вводе пароля: {e}", reply_markup=back_kb("menu:sessions"))
        await state.clear()
        _qr_sessions.pop(db_user.tg_id, None)
        return
    _qr_sessions.pop(db_user.tg_id, None)
    await _save_session(db_user.tg_id, message.chat.id, state, auth_result, message)


# ── Phone Login flow ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "session:add:phone")
async def cb_session_add_phone(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message
    await state.clear()
    text = "📞 <b>Авторизация по номеру</b>\n\nВведи номер в формате <code>+7XXXXXXXXXX</code>:"
    try:
        await callback.message.edit_text(text, reply_markup=back_kb("menu:sessions"))
    except Exception:
        await callback.message.answer(text, reply_markup=back_kb("menu:sessions"))
    await state.set_state(SessionAddPhone.waiting_phone)
    await callback.answer()


@router.message(SessionAddPhone.waiting_phone)
async def fsm_phone_number(message: Message, state: FSMContext, db_user: User) -> None:
    phone = (message.text or "").strip()
    if not phone.startswith("+") or len(phone) < 8:
        await message.answer("Неверный формат. Нужно <code>+7XXXXXXXXXX</code>:")
        return
    auth = PhoneLoginSession()
    _phone_sessions[db_user.tg_id] = auth

    status = await message.answer("⏳ Отправляю код...")
    success, error = await auth.send_code(phone)
    if not success:
        _phone_sessions.pop(db_user.tg_id, None)
        await auth.cancel()
        await state.clear()
        await status.edit_text(f"❌ {error}", reply_markup=phone_retry_kb())
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


# ── Health check ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("session:check:"))
async def cb_session_check(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    session_id = callback.data.split(":", 2)[2]
    await callback.answer("⏳ Проверяю...", show_alert=False)

    async with async_session_factory() as session:
        repo = SessionRepository(session)
        tg_session = await repo.get(uuid.UUID(session_id))

    if not tg_session:
        await callback.message.edit_text("❌ Сессия не найдена.")
        return

    pool = SessionPool()
    try:
        is_alive = await pool.health_check(tg_session)
    finally:
        await pool.disconnect_all()

    async with async_session_factory() as db_session:
        async with db_session.begin():
            repo2 = SessionRepository(db_session)
            await repo2.update(tg_session.id, is_active=is_alive)

    async with async_session_factory() as session:
        repo = SessionRepository(session)
        tg_session = await repo.get(uuid.UUID(session_id))

    assert tg_session
    await callback.message.edit_text(
        _render_session_view(tg_session), reply_markup=session_view_kb(session_id)
    )


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
    """Persist auth_result and *always* reply to the user, even on partial failure."""
    from bot.core.bot import bot

    async def _reply(text: str, *, show_back: bool = True) -> None:
        kb = back_kb("menu:sessions") if show_back else None
        try:
            if message is not None:
                await message.answer(text, reply_markup=kb)
            else:
                await bot.send_message(chat_id, text, reply_markup=kb)
        except Exception:
            log.exception("Failed to deliver session reply", user_id=user_id)

    try:
        await state.clear()
    except Exception:
        pass

    if not auth_result.success:
        log.warning("Session auth failed", user_id=user_id, error=auth_result.error)
        await _reply(f"❌ Ошибка авторизации: {auth_result.error}")
        return

    session_name = _default_session_name(auth_result)

    try:
        async with async_session_factory() as db_session:
            async with db_session.begin():
                repo = SessionRepository(db_session)
                await repo.create(
                    user_id=user_id,
                    name=session_name,
                    encrypted_session=auth_result.encrypted_session,
                    phone=auth_result.phone,
                    has_premium=auth_result.has_premium,
                    account_name=auth_result.account_name,
                    account_username=auth_result.account_username,
                )
    except Exception as e:
        log.exception("Session DB save failed", user_id=user_id)
        await _reply(f"❌ Сессия авторизована, но не сохранилась в БД: {e}")
        return

    premium = "💎 Premium" if auth_result.has_premium else "нет"
    text = (
        f"✅ <b>Сессия добавлена!</b>\n\n"
        f"📱 {session_name}\n"
        f"👤 {auth_result.account_name or '—'}\n"
        f"⭐ Premium: {premium}\n\n"
        f"<i>Переименовать можно в карточке сессии.</i>"
    )
    log.info("Session saved", user_id=user_id, name=session_name)
    await _reply(text)
