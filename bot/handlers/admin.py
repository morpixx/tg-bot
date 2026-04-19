from __future__ import annotations

import uuid

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.filters.admin import IsOwner
from bot.keyboards.utils import back_kb
from bot.states.fsm import AdminNotify
from db.models import CampaignStatus
from db.repositories.campaign_repo import CampaignRepository
from db.repositories.session_repo import SessionRepository
from db.repositories.user_repo import UserRepository
from db.session import async_session_factory

router = Router()
# Apply IsOwner filter to every handler in this router
router.message.filter(IsOwner())
router.callback_query.filter(IsOwner())


# ── /admin — owner panel ──────────────────────────────────────────────────────

def _admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Операторы", callback_data="admin:operators")],
            [InlineKeyboardButton(text="📢 Все активные кампании", callback_data="admin:campaigns")],
            [InlineKeyboardButton(text="📨 Рассылка по пользователям", callback_data="admin:notify")],
        ]
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    async with async_session_factory() as session:
        user_repo = UserRepository(session)
        users = await user_repo.list_active()
    await message.answer(
        f"🔧 <b>Панель владельца</b>\n\n"
        f"Операторов: <b>{len(users)}</b>",
        reply_markup=_admin_menu_kb(),
    )


@router.callback_query(F.data == "admin:panel")
async def cb_admin_panel(callback: CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return
    async with async_session_factory() as session:
        user_repo = UserRepository(session)
        users = await user_repo.list_active()
    await callback.message.edit_text(
        f"🔧 <b>Панель владельца</b>\n\nОператоров: <b>{len(users)}</b>",
        reply_markup=_admin_menu_kb(),
    )
    await callback.answer()


# ── Operators list ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:operators")
async def cb_admin_operators(callback: CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return
    async with async_session_factory() as session:
        user_repo = UserRepository(session)
        users = await user_repo.list_active()

    if not users:
        await callback.message.edit_text("👥 Нет операторов.", reply_markup=back_kb("admin:panel"))
        await callback.answer()
        return

    rows = []
    for u in users:
        name = u.username and f"@{u.username}" or u.full_name or str(u.tg_id)
        rows.append([InlineKeyboardButton(
            text=f"👤 {name}",
            callback_data=f"admin:operator:{u.tg_id}",
        )])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin:panel")])

    await callback.message.edit_text(
        f"👥 <b>Операторы</b> ({len(users)}):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:operator:"))
async def cb_admin_operator_detail(callback: CallbackQuery) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    operator_id = int(callback.data.split(":", 2)[2])

    async with async_session_factory() as session:
        user_repo = UserRepository(session)
        session_repo = SessionRepository(session)
        campaign_repo = CampaignRepository(session)

        user = await user_repo.get(operator_id)
        sessions = await session_repo.get_by_user(operator_id)
        campaigns = await campaign_repo.get_by_user(operator_id)

    if not user:
        await callback.answer("Оператор не найден", show_alert=True)
        return

    name = user.username and f"@{user.username}" or user.full_name or str(user.tg_id)
    active_campaigns = [c for c in campaigns if c.status == CampaignStatus.ACTIVE]
    session_lines = "\n".join(
        f"  {'💎' if s.has_premium else '📱'} {s.name} — {s.account_username and '@' + s.account_username or s.phone or '—'}"
        for s in sessions
    ) or "  нет сессий"

    text = (
        f"👤 <b>{name}</b>\n"
        f"ID: <code>{user.tg_id}</code>\n\n"
        f"📱 Сессий: {len(sessions)}\n"
        f"{session_lines}\n\n"
        f"📢 Кампаний: {len(campaigns)} (активных: {len(active_campaigns)})"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"admin:block:{operator_id}")],
        [InlineKeyboardButton(text="⏹ Остановить все кампании", callback_data=f"admin:stopall:{operator_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:operators")],
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("admin:block:"))
async def cb_admin_block(callback: CallbackQuery) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    operator_id = int(callback.data.split(":", 2)[2])
    async with async_session_factory() as session:
        async with session.begin():
            repo = UserRepository(session)
            await repo.update(operator_id, is_active=False)
    await callback.message.edit_text(
        f"🚫 Пользователь <code>{operator_id}</code> заблокирован.",
        reply_markup=back_kb("admin:operators"),
    )
    await callback.answer()


# ── Force-stop all campaigns of an operator ───────────────────────────────────

@router.callback_query(F.data.startswith("admin:stopall:"))
async def cb_admin_stop_all(callback: CallbackQuery) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    operator_id = int(callback.data.split(":", 2)[2])

    async with async_session_factory() as session:
        repo = CampaignRepository(session)
        campaigns = await repo.get_by_user(operator_id)
        active = [c for c in campaigns if c.status == CampaignStatus.ACTIVE]

    stopped = 0
    for campaign in active:
        from worker.broadcaster import request_stop
        request_stop(campaign.id)
        async with async_session_factory() as session:
            async with session.begin():
                repo = CampaignRepository(session)
                await repo.update_status(campaign.id, CampaignStatus.STOPPED)
        stopped += 1

    await callback.message.edit_text(
        f"⏹ Остановлено кампаний: <b>{stopped}</b>",
        reply_markup=back_kb(f"admin:operator:{operator_id}"),
    )
    await callback.answer()


# ── All active campaigns (across all operators) ───────────────────────────────

@router.callback_query(F.data == "admin:campaigns")
async def cb_admin_all_campaigns(callback: CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return
    async with async_session_factory() as session:
        repo = CampaignRepository(session)
        active = await repo.get_active()

    if not active:
        await callback.message.edit_text(
            "📢 Нет активных кампаний.", reply_markup=back_kb("admin:panel")
        )
        await callback.answer()
        return

    rows = []
    for c in active:
        rows.append([InlineKeyboardButton(
            text=f"▶️ {c.name} (uid:{c.user_id})",
            callback_data=f"admin:forcestop:{c.id}",
        )])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin:panel")])

    await callback.message.edit_text(
        f"📢 <b>Активные кампании</b> ({len(active)})\n\nНажми на кампанию чтобы остановить:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:forcestop:"))
async def cb_admin_force_stop(callback: CallbackQuery) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    campaign_id = uuid.UUID(callback.data.split(":", 2)[2])

    from worker.broadcaster import request_stop
    request_stop(campaign_id)

    async with async_session_factory() as session:
        async with session.begin():
            repo = CampaignRepository(session)
            await repo.update_status(campaign_id, CampaignStatus.STOPPED)

    await callback.message.edit_text(
        f"⏹ Кампания <code>{campaign_id}</code> остановлена.",
        reply_markup=back_kb("admin:campaigns"),
    )
    await callback.answer()


# ── /notify_all — broadcast message to all users ─────────────────────────────

@router.message(Command("notify_all"))
async def cmd_notify_all(message: Message, state: FSMContext) -> None:
    await message.answer(
        "📨 <b>Рассылка всем пользователям</b>\n\n"
        "Отправь сообщение (текст, фото, видео — любой тип).\n"
        "Оно будет переслано каждому оператору бота.\n\n"
        "Отправь /cancel для отмены."
    )
    await state.set_state(AdminNotify.waiting_message)


@router.callback_query(F.data == "admin:notify")
async def cb_admin_notify(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return
    await callback.message.edit_text(
        "📨 <b>Рассылка всем пользователям</b>\n\n"
        "Отправь сообщение (текст, фото, видео — любой тип).\n"
        "Отправь /cancel для отмены."
    )
    await state.set_state(AdminNotify.waiting_message)
    await callback.answer()


@router.message(Command("cancel"), AdminNotify.waiting_message)
async def cmd_cancel_notify(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Рассылка отменена.", reply_markup=back_kb("admin:panel"))


@router.message(AdminNotify.waiting_message)
async def fsm_admin_notify_message(message: Message, state: FSMContext) -> None:
    import asyncio

    await state.clear()

    async with async_session_factory() as session:
        repo = UserRepository(session)
        users = await repo.list_active()

    status_msg = await message.answer(f"⏳ Отправляю {len(users)} пользователям...")

    sent = 0
    failed = 0
    # Telegram global bot API limit is ~30 msg/sec; keep well below it.
    for user in users:
        try:
            await message.copy_to(user.tg_id)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        f"📨 <b>Рассылка завершена</b>\n\n"
        f"✅ Доставлено: {sent}\n"
        f"❌ Ошибок: {failed}",
        reply_markup=back_kb("admin:panel"),
    )
