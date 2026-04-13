from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from bot.keyboards.main_menu import main_menu_kb
from services.subscription import check_subscriptions

router = Router()

WELCOME_TEXT = (
    "👋 <b>Привет, {name}!</b>\n\n"
    "Я бот для управления рассылкой по Telegram-чатам.\n\n"
    "Используй меню ниже для управления:"
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    assert message.from_user
    name = message.from_user.full_name or message.from_user.username or "Пользователь"
    await message.answer(WELCOME_TEXT.format(name=name), reply_markup=main_menu_kb())


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery) -> None:
    assert callback.message
    await callback.message.edit_text(
        "🏠 <b>Главное меню</b>",
        reply_markup=main_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "check_subscription")
async def cb_check_subscription(callback: CallbackQuery) -> None:
    assert callback.from_user and callback.message
    subscribed, _ = await check_subscriptions(callback.bot, callback.from_user.id)
    if subscribed:
        await callback.message.edit_text(
            "✅ <b>Подписка подтверждена!</b>\n\nДобро пожаловать 🎉",
            reply_markup=main_menu_kb(),
        )
    else:
        await callback.answer("Вы ещё не подписались на все каналы!", show_alert=True)


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()
