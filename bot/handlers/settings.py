from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.settings_kb import global_settings_kb
from bot.keyboards.utils import cancel_kb, remember_prompt, reprompt
from bot.states.fsm import GlobalSettingsEdit
from db.models import User
from db.repositories.user_settings_repo import UserSettingsRepository
from db.session import async_session_factory

router = Router()

_TOGGLE_FIELDS = {"randomize_delay", "shuffle_after_cycle", "forward_mode", "cycle_delay_randomize"}

_PROMPTS: dict[str, str] = {
    "delay_between_chats": "⏱ Введи задержку между чатами в секундах (например: <code>5</code>):",
    "randomize_min": "🎲 Введи минимальную задержку рандома между чатами в секундах (например: <code>3</code>):",
    "randomize_max": "🎲 Введи максимальную задержку рандома между чатами в секундах (например: <code>10</code>):",
    "shuffle_after_cycle": "🔀 Перемешивать список чатов после каждого цикла?\nВведи: <code>да</code> или <code>нет</code>",
    "delay_between_cycles": "🔄 Введи задержку между циклами в секундах (например: <code>60</code>):",
    "cycle_delay_min": "🎲 Введи минимальную задержку рандома между циклами в секундах (например: <code>30</code>):",
    "cycle_delay_max": "🎲 Введи максимальную задержку рандома между циклами в секундах (например: <code>120</code>):",
    "max_cycles": "🔁 Введи максимальное число циклов (<code>0</code> = бесконечно):",
    "forward_mode": "📤 Режим отправки:\n<code>1</code> — Форвард (со ссылкой на источник)\n<code>2</code> — Копия (без атрибуции)\nВведи 1 или 2:",
}


@router.callback_query(F.data == "menu:settings")
async def cb_settings(callback: CallbackQuery, db_user: User) -> None:
    if not callback.message:
        await callback.answer()
        return
    async with async_session_factory() as session:
        repo = UserSettingsRepository(session)
        cfg = await repo.get_or_create(db_user.tg_id)
    await callback.message.edit_text(
        "⚙️ <b>Глобальные настройки кампаний</b>\n\n"
        "Эти значения применяются по умолчанию при создании каждой новой кампании.\n"
        "Для каждой кампании настройки можно изменить отдельно.",
        reply_markup=global_settings_kb(cfg),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("gs:"))
async def cb_setting_select(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    field = callback.data.split(":", 1)[1]

    # Toggle booleans inline without asking for input
    if field in _TOGGLE_FIELDS:
        async with async_session_factory() as session:
            async with session.begin():
                repo = UserSettingsRepository(session)
                cfg = await repo.get_or_create(db_user.tg_id)
                current = getattr(cfg, field)
                await repo.update(db_user.tg_id, **{field: not current})
                cfg = await repo.get_or_create(db_user.tg_id)
        await callback.message.edit_reply_markup(reply_markup=global_settings_kb(cfg))
        await callback.answer("Сохранено")
        return

    prompt = _PROMPTS.get(field, "Введи значение:")
    await state.update_data(gs_field=field)
    sent = await callback.message.edit_text(prompt, reply_markup=cancel_kb("menu:settings"))
    await remember_prompt(state, sent)
    await state.set_state(GlobalSettingsEdit.waiting_value)
    await callback.answer()


@router.message(GlobalSettingsEdit.waiting_value)
async def fsm_gs_value(message: Message, state: FSMContext, db_user: User) -> None:
    data = await state.get_data()
    field = data["gs_field"]
    raw = (message.text or "").strip().lower()

    try:
        if field in ("delay_between_chats", "delay_between_cycles", "randomize_min", "randomize_max",
                     "cycle_delay_min", "cycle_delay_max"):
            value: object = int(raw)
            if int(raw) < 0:
                raise ValueError
        elif field == "max_cycles":
            value = int(raw) or None
        elif field == "forward_mode":
            value = raw == "1"
        else:
            value = raw
    except (ValueError, KeyError):
        await reprompt(message, state, "⚠️ Неверный формат. Попробуй ещё раз:", reply_markup=cancel_kb("menu:settings"))
        return

    async with async_session_factory() as session:
        async with session.begin():
            repo = UserSettingsRepository(session)
            await repo.update(db_user.tg_id, **{field: value})
            cfg = await repo.get_or_create(db_user.tg_id)

    await state.clear()
    await message.answer(
        "✅ Настройка сохранена.",
        reply_markup=global_settings_kb(cfg),
    )
