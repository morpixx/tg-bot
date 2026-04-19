from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from bot.core.config import settings
from bot.keyboards.main_menu import main_menu_kb
from db.models import Campaign, CampaignStatus, TargetChat, TelegramSession
from db.session import async_session_factory
from services.subscription import check_subscriptions

router = Router()


async def _dashboard(tg_id: int) -> str:
    """Build the dashboard header with live counts. One async DB round-trip."""
    async with async_session_factory() as session:
        sessions_total = await session.scalar(
            select(func.count(TelegramSession.id)).where(TelegramSession.user_id == tg_id)
        ) or 0
        sessions_active = await session.scalar(
            select(func.count(TelegramSession.id)).where(
                TelegramSession.user_id == tg_id,
                TelegramSession.is_active.is_(True),
            )
        ) or 0
        campaigns_active = await session.scalar(
            select(func.count(Campaign.id)).where(
                Campaign.user_id == tg_id,
                Campaign.status == CampaignStatus.ACTIVE,
            )
        ) or 0
        chats_total = await session.scalar(
            select(func.count(TargetChat.id)).where(TargetChat.user_id == tg_id)
        ) or 0

    return (
        f"📱 Сессий: <b>{sessions_active}/{sessions_total}</b>   "
        f"💬 Чатов: <b>{chats_total}</b>\n"
        f"📢 Активных кампаний: <b>{campaigns_active}</b>"
    )


async def _menu_text(name: str, tg_id: int) -> str:
    header = await _dashboard(tg_id)
    return f"🏠 <b>Главное меню</b>\n\n{header}\n\nПривет, {name}! Выбери раздел ниже:"


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    assert message.from_user
    await state.clear()
    name = message.from_user.full_name or message.from_user.username or "Пользователь"
    is_owner = message.from_user.id == settings.owner_id
    text = await _menu_text(name, message.from_user.id)
    await message.answer(text, reply_markup=main_menu_kb(is_owner=is_owner))


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    """Universal entry point — works from any FSM state."""
    assert message.from_user
    await state.clear()
    name = message.from_user.full_name or message.from_user.username or "Пользователь"
    is_owner = message.from_user.id == settings.owner_id
    text = await _menu_text(name, message.from_user.id)
    await message.answer(text, reply_markup=main_menu_kb(is_owner=is_owner))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Abort any in-progress flow and return to main menu."""
    assert message.from_user
    current = await state.get_state()
    await state.clear()
    name = message.from_user.full_name or message.from_user.username or "Пользователь"
    is_owner = message.from_user.id == settings.owner_id
    text = await _menu_text(name, message.from_user.id)
    prefix = "✅ Действие отменено.\n\n" if current else ""
    await message.answer(prefix + text, reply_markup=main_menu_kb(is_owner=is_owner))


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        await callback.answer()
        return
    is_owner = callback.from_user.id == settings.owner_id
    name = callback.from_user.full_name or callback.from_user.username or "Пользователь"
    text = await _menu_text(name, callback.from_user.id)
    try:
        await callback.message.edit_text(text, reply_markup=main_menu_kb(is_owner=is_owner))
    except Exception:
        await callback.message.answer(text, reply_markup=main_menu_kb(is_owner=is_owner))
    await callback.answer()


@router.callback_query(F.data == "check_subscription")
async def cb_check_subscription(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message or not callback.bot:
        await callback.answer()
        return
    subscribed, _ = await check_subscriptions(callback.bot, callback.from_user.id)
    if subscribed:
        is_owner = callback.from_user.id == settings.owner_id
        name = callback.from_user.full_name or callback.from_user.username or "Пользователь"
        text = await _menu_text(name, callback.from_user.id)
        await callback.message.edit_text(text, reply_markup=main_menu_kb(is_owner=is_owner))
    else:
        await callback.answer("Вы ещё не подписались на все каналы!", show_alert=True)


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()
