from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.settings_kb import global_settings_kb
from bot.states.fsm import GlobalSettingsEdit
from db.models import User
from db.repositories.user_settings_repo import UserSettingsRepository
from db.session import async_session_factory

router = Router()

_PROMPTS: dict[str, str] = {
    "delay_between_chats": "Введи задержку между чатами в секундах (например: <code>5</code>):",
    "randomize_delay": "Рандомизировать задержку?\nВведи: <code>да</code> или <code>нет</code>",
    "randomize_min": "Введи минимальную задержку рандома в секундах (например: <code>3</code>):",
    "randomize_max": "Введи максимальную задержку рандома в секундах (например: <code>10</code>):",
    "shuffle_after_cycle": "Перемешивать список чатов после каждого цикла?\nВведи: <code>да</code> или <code>нет</code>",
    "delay_between_cycles": "Введи задержку между циклами в секундах (например: <code>60</code>):",
    "max_cycles": "Введи максимальное число циклов (0 = бесконечно):",
    "forward_mode": "Режим отправки:\n<code>1</code> — Форвард (со ссылкой на источник)\n<code>2</code> — Копия (без атрибуции)\nВведи 1 или 2:",
}

_BOOL_MAP = {"да": True, "нет": False, "yes": True, "no": False}


@router.callback_query(F.data == "menu:settings")
async def cb_settings(callback: CallbackQuery, db_user: User) -> None:
    assert callback.message
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
    assert callback.message and callback.data
    field = callback.data.split(":", 1)[1]

    # Toggle booleans inline without asking for input
    if field in ("randomize_delay", "shuffle_after_cycle", "forward_mode"):
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

    await state.update_data(gs_field=field)
    await callback.message.edit_text(_PROMPTS[field])
    await state.set_state(GlobalSettingsEdit.waiting_value)
    await callback.answer()


@router.message(GlobalSettingsEdit.waiting_value)
async def fsm_gs_value(message: Message, state: FSMContext, db_user: User) -> None:
    data = await state.get_data()
    field = data["gs_field"]
    raw = (message.text or "").strip().lower()

    try:
        if field in ("delay_between_chats", "delay_between_cycles", "randomize_min", "randomize_max"):
            value: object = int(raw)
            if value < 0:
                raise ValueError
        elif field == "max_cycles":
            value = int(raw) or None
        else:
            value = raw
    except (ValueError, KeyError):
        await message.answer("⚠️ Неверный формат. Попробуй ещё раз:")
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
