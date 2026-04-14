from __future__ import annotations

import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.campaigns_kb import (
    campaign_settings_kb,
    campaign_view_kb,
    campaigns_list_kb,
    chat_select_kb,
    session_select_kb,
)
from bot.keyboards.posts_kb import posts_list_kb
from bot.keyboards.utils import back_kb
from bot.states.fsm import CampaignCreate, CampaignSettingsEdit
from db.models import CampaignStatus, User
from db.repositories.campaign_repo import CampaignRepository
from db.repositories.chat_repo import ChatRepository
from db.repositories.post_repo import PostRepository
from db.repositories.session_repo import SessionRepository
from db.repositories.user_settings_repo import UserSettingsRepository
from db.session import async_session_factory

router = Router()


# ── List ──────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:campaigns")
async def cb_campaigns_list(callback: CallbackQuery, db_user: User) -> None:
    assert callback.message
    async with async_session_factory() as session:
        repo = CampaignRepository(session)
        campaigns = await repo.get_by_user(db_user.tg_id)
    await callback.message.edit_text(
        f"📢 <b>Кампании</b> ({len(campaigns)})",
        reply_markup=campaigns_list_kb(campaigns),
    )
    await callback.answer()


# ── View ──────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("campaign:view:"))
async def cb_campaign_view(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    campaign_id = callback.data.split(":", 2)[2]
    async with async_session_factory() as session:
        repo = CampaignRepository(session)
        campaign = await repo.get(uuid.UUID(campaign_id), load_relations=True)
    if not campaign:
        await callback.answer("Кампания не найдена", show_alert=True)
        return
    sessions_count = len(campaign.campaign_sessions)
    chats_count = len(campaign.campaign_chats)
    status_label = {
        CampaignStatus.DRAFT: "📋 Черновик",
        CampaignStatus.ACTIVE: "▶️ Активна",
        CampaignStatus.PAUSED: "⏸ Пауза",
        CampaignStatus.STOPPED: "⏹ Остановлена",
        CampaignStatus.COMPLETED: "✅ Завершена",
    }.get(campaign.status, "❓")
    text = (
        f"📢 <b>{campaign.name}</b>\n\n"
        f"Статус: {status_label}\n"
        f"Пост: {campaign.post.title if campaign.post else '—'}\n"
        f"Сессий: {sessions_count}\n"
        f"Чатов: {chats_count}\n"
        f"Цикл: {campaign.current_cycle}"
    )
    await callback.message.edit_text(
        text,
        reply_markup=campaign_view_kb(campaign_id, campaign.status),
    )
    await callback.answer()


# ── Create campaign wizard ────────────────────────────────────────────────────

@router.callback_query(F.data == "campaign:create")
async def cb_campaign_create(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    assert callback.message
    await state.clear()
    await callback.message.edit_text("📢 <b>Новая кампания</b>\n\nВведи название:")
    await state.set_state(CampaignCreate.waiting_name)
    await callback.answer()


@router.message(CampaignCreate.waiting_name)
async def fsm_campaign_name(message: Message, state: FSMContext, db_user: User) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название не может быть пустым:")
        return
    await state.update_data(campaign_name=name)

    async with async_session_factory() as session:
        repo = PostRepository(session)
        posts = await repo.get_by_user(db_user.tg_id)
    if not posts:
        await message.answer(
            "⚠️ У тебя нет постов. Сначала добавь хотя бы один пост.",
            reply_markup=back_kb("menu:campaigns"),
        )
        await state.clear()
        return
    await message.answer(
        "📝 <b>Выбери пост для рассылки:</b>",
        reply_markup=posts_list_kb(posts),
    )
    await state.set_state(CampaignCreate.waiting_post)


@router.callback_query(F.data.startswith("post:view:"), CampaignCreate.waiting_post)
async def fsm_campaign_post(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    assert callback.message and callback.data
    post_id = callback.data.split(":", 2)[2]
    await state.update_data(post_id=post_id, selected_sessions=[], selected_chats=[])

    async with async_session_factory() as session:
        repo = SessionRepository(session)
        sessions = await repo.get_by_user(db_user.tg_id)
    if not sessions:
        await callback.message.edit_text(
            "⚠️ Нет активных сессий. Добавь хотя бы одну.",
            reply_markup=back_kb("menu:campaigns"),
        )
        await state.clear()
        await callback.answer()
        return
    await callback.message.edit_text(
        "📱 <b>Выбери сессии для рассылки:</b>\n\n(Можно выбрать несколько)",
        reply_markup=session_select_kb(sessions, set()),
    )
    await state.set_state(CampaignCreate.waiting_sessions)
    await callback.answer()


@router.callback_query(F.data.startswith("csel:session:"), CampaignCreate.waiting_sessions)
async def fsm_toggle_session(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    assert callback.data
    session_id = callback.data.split(":", 2)[2]
    data = await state.get_data()
    selected: list[str] = list(data.get("selected_sessions", []))
    if session_id in selected:
        selected.remove(session_id)
    else:
        selected.append(session_id)
    await state.update_data(selected_sessions=selected)

    async with async_session_factory() as session:
        repo = SessionRepository(session)
        sessions = await repo.get_by_user(db_user.tg_id)
    assert callback.message
    await callback.message.edit_reply_markup(
        reply_markup=session_select_kb(sessions, set(selected))
    )
    await callback.answer()


@router.callback_query(F.data == "csel:sessions:done", CampaignCreate.waiting_sessions)
async def fsm_sessions_done(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    assert callback.message
    data = await state.get_data()
    if not data.get("selected_sessions"):
        await callback.answer("Выбери хотя бы одну сессию!", show_alert=True)
        return

    async with async_session_factory() as session:
        repo = ChatRepository(session)
        chats = await repo.get_by_user(db_user.tg_id)
    if not chats:
        await callback.message.edit_text(
            "⚠️ Нет чатов. Добавь хотя бы один чат в раздел «Чаты».",
            reply_markup=back_kb("menu:campaigns"),
        )
        await state.clear()
        await callback.answer()
        return

    await callback.message.edit_text(
        "💬 <b>Выбери чаты для рассылки:</b>",
        reply_markup=chat_select_kb(chats, set()),
    )
    await state.set_state(CampaignCreate.waiting_chats)
    await callback.answer()


@router.callback_query(F.data.startswith("csel:chat:"), CampaignCreate.waiting_chats)
async def fsm_toggle_chat(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    assert callback.data
    chat_id = callback.data.split(":", 2)[2]
    data = await state.get_data()
    selected: list[str] = list(data.get("selected_chats", []))
    if chat_id in selected:
        selected.remove(chat_id)
    else:
        selected.append(chat_id)
    await state.update_data(selected_chats=selected)

    async with async_session_factory() as session:
        repo = ChatRepository(session)
        chats = await repo.get_by_user(db_user.tg_id)
    assert callback.message
    await callback.message.edit_reply_markup(
        reply_markup=chat_select_kb(chats, set(selected))
    )
    await callback.answer()


@router.callback_query(F.data == "csel:chats:all", CampaignCreate.waiting_chats)
async def fsm_select_all_chats(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    async with async_session_factory() as session:
        repo = ChatRepository(session)
        chats = await repo.get_by_user(db_user.tg_id)
    all_ids = [str(c.id) for c in chats]
    await state.update_data(selected_chats=all_ids)
    assert callback.message
    await callback.message.edit_reply_markup(
        reply_markup=chat_select_kb(chats, set(all_ids))
    )
    await callback.answer("Выбраны все чаты")


@router.callback_query(F.data == "csel:chats:done", CampaignCreate.waiting_chats)
async def fsm_chats_done(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    assert callback.message
    data = await state.get_data()
    if not data.get("selected_chats"):
        await callback.answer("Выбери хотя бы один чат!", show_alert=True)
        return

    # Create campaign in DB
    async with async_session_factory() as session:
        async with session.begin():
            repo = CampaignRepository(session)
            gs_repo = UserSettingsRepository(session)
            gs = await gs_repo.get_or_create(db_user.tg_id)
            defaults = {
                "delay_between_chats": gs.delay_between_chats,
                "randomize_delay": gs.randomize_delay,
                "randomize_min": gs.randomize_min,
                "randomize_max": gs.randomize_max,
                "shuffle_after_cycle": gs.shuffle_after_cycle,
                "delay_between_cycles": gs.delay_between_cycles,
                "max_cycles": gs.max_cycles,
                "forward_mode": gs.forward_mode,
            }
            campaign = await repo.create(
                user_id=db_user.tg_id,
                name=data["campaign_name"],
                post_id=uuid.UUID(data["post_id"]),
                defaults=defaults,
            )
            # Set sessions (default offset=0)
            await repo.set_sessions(
                campaign.id,
                {uuid.UUID(sid): 0 for sid in data["selected_sessions"]},
            )
            # Set chats
            await repo.set_chats(campaign.id, [uuid.UUID(cid) for cid in data["selected_chats"]])
            campaign_id = str(campaign.id)

    await state.clear()
    await callback.message.edit_text(
        f"✅ <b>Кампания создана!</b>\n\n"
        f"📢 {data['campaign_name']}\n\n"
        f"Теперь можешь настроить параметры или сразу запустить.",
        reply_markup=campaign_view_kb(campaign_id, CampaignStatus.DRAFT),
    )
    await callback.answer()


# ── Settings ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("campaign:settings:"))
async def cb_campaign_settings(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    campaign_id = callback.data.split(":", 2)[2]
    async with async_session_factory() as session:
        repo = CampaignRepository(session)
        campaign = await repo.get(uuid.UUID(campaign_id), load_relations=True)
    if not campaign or not campaign.settings:
        await callback.answer("Кампания не найдена", show_alert=True)
        return
    cfg = campaign.settings
    text = (
        f"⚙️ <b>Настройки кампании</b>\n\n"
        f"⏱ Задержка между чатами: {cfg.delay_between_chats} сек\n"
        f"🎲 Рандомизация: {'да' if cfg.randomize_delay else 'нет'} "
        f"({cfg.randomize_min}–{cfg.randomize_max} сек)\n"
        f"🔀 Перемешивать список: {'да' if cfg.shuffle_after_cycle else 'нет'}\n"
        f"🔄 Задержка между циклами: {cfg.delay_between_cycles} сек\n"
        f"🔁 Макс. циклов: {cfg.max_cycles or '∞'}\n"
        f"📤 Режим: {'Форвард' if cfg.forward_mode else 'Копия'}"
    )
    await callback.message.edit_text(text, reply_markup=campaign_settings_kb(campaign_id))
    await callback.answer()


@router.callback_query(F.data.startswith("csetting:"))
async def cb_setting_edit(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.data and callback.message
    parts = callback.data.split(":")
    field = parts[1]
    campaign_id = parts[2]

    prompts = {
        "delay_between_chats": "Введи задержку между чатами в секундах (например: 5):",
        "randomize_delay": "Рандомизировать задержку? Введи: да/нет",
        "shuffle_after_cycle": "Перемешивать список после цикла? Введи: да/нет",
        "delay_between_cycles": "Введи задержку между циклами в секундах (например: 60):",
        "max_cycles": "Введи максимальное количество циклов (0 = бесконечно):",
        "forward_mode": "Режим отправки:\n1 — Форвард (с подписью)\n2 — Копия (без подписи)\nВведи 1 или 2:",
    }
    await state.update_data(setting_field=field, setting_campaign_id=campaign_id)
    await callback.message.edit_text(prompts.get(field, "Введи значение:"))
    await state.set_state(CampaignSettingsEdit.waiting_value)
    await callback.answer()


@router.message(CampaignSettingsEdit.waiting_value)
async def fsm_setting_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field = data["setting_field"]
    campaign_id = uuid.UUID(data["setting_campaign_id"])
    raw = (message.text or "").strip().lower()

    bool_map = {"да": True, "нет": False, "yes": True, "no": False, "1": True, "2": False}

    try:
        if field in ("delay_between_chats", "delay_between_cycles"):
            value: object = int(raw)
        elif field == "max_cycles":
            value = int(raw) or None
        elif field in ("randomize_delay", "shuffle_after_cycle"):
            value = bool_map.get(raw)
            if value is None:
                raise ValueError
        elif field == "forward_mode":
            value = raw == "1"
        else:
            value = raw
    except (ValueError, KeyError):
        await message.answer("⚠️ Неверный формат. Попробуй ещё раз:")
        return

    async with async_session_factory() as session:
        async with session.begin():
            repo = CampaignRepository(session)
            await repo.update_settings(campaign_id, **{field: value})

    await state.clear()
    await message.answer(
        "✅ Настройка сохранена.",
        reply_markup=back_kb(f"campaign:settings:{campaign_id}"),
    )


# ── Control (start / pause / resume / stop) ────────────────────────────────────

@router.callback_query(F.data.startswith("campaign:start:"))
async def cb_campaign_start(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    from datetime import datetime, timezone
    campaign_id = callback.data.split(":", 2)[2]
    async with async_session_factory() as session:
        async with session.begin():
            repo = CampaignRepository(session)
            campaign = await repo.get(uuid.UUID(campaign_id))
            if campaign:
                campaign.status = CampaignStatus.ACTIVE
                campaign.started_at = datetime.now(timezone.utc)
    await callback.message.edit_text(
        "▶️ <b>Кампания запущена!</b>\n\nВоркер начнёт рассылку в течение нескольких секунд.",
        reply_markup=campaign_view_kb(campaign_id, CampaignStatus.ACTIVE),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("campaign:pause:"))
async def cb_campaign_pause(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    campaign_id = callback.data.split(":", 2)[2]
    async with async_session_factory() as session:
        async with session.begin():
            repo = CampaignRepository(session)
            await repo.update_status(uuid.UUID(campaign_id), CampaignStatus.PAUSED)
    await callback.message.edit_text(
        "⏸ <b>Кампания приостановлена.</b>",
        reply_markup=campaign_view_kb(campaign_id, CampaignStatus.PAUSED),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("campaign:resume:"))
async def cb_campaign_resume(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    campaign_id = callback.data.split(":", 2)[2]
    async with async_session_factory() as session:
        async with session.begin():
            repo = CampaignRepository(session)
            await repo.update_status(uuid.UUID(campaign_id), CampaignStatus.ACTIVE)
    await callback.message.edit_text(
        "▶️ <b>Кампания возобновлена!</b>",
        reply_markup=campaign_view_kb(campaign_id, CampaignStatus.ACTIVE),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("campaign:stop:"))
async def cb_campaign_stop(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    campaign_id = callback.data.split(":", 2)[2]
    async with async_session_factory() as session:
        async with session.begin():
            repo = CampaignRepository(session)
            await repo.update_status(uuid.UUID(campaign_id), CampaignStatus.STOPPED)
    await callback.message.edit_text(
        "⏹ <b>Кампания остановлена.</b>",
        reply_markup=campaign_view_kb(campaign_id, CampaignStatus.STOPPED),
    )
    await callback.answer()


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("campaign:stats:"))
async def cb_campaign_stats(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    from sqlalchemy import func, select
    from db.models import BroadcastLog, BroadcastStatus

    campaign_id = uuid.UUID(callback.data.split(":", 2)[2])
    async with async_session_factory() as session:
        # Aggregate by status
        result = await session.execute(
            select(BroadcastLog.status, func.count())
            .where(BroadcastLog.campaign_id == campaign_id)
            .group_by(BroadcastLog.status)
        )
        stats = dict(result.all())

    success = stats.get(BroadcastStatus.SUCCESS, 0)
    failed = stats.get(BroadcastStatus.FAILED, 0)
    flood = stats.get(BroadcastStatus.FLOOD_WAIT, 0)
    skipped = stats.get(BroadcastStatus.SKIPPED, 0)
    total = success + failed + flood + skipped

    text = (
        f"📈 <b>Статистика кампании</b>\n\n"
        f"✅ Успешно: {success}\n"
        f"❌ Ошибок: {failed}\n"
        f"⏳ Flood wait: {flood}\n"
        f"⏭ Пропущено: {skipped}\n"
        f"📊 Всего: {total}"
    )
    cid = str(campaign_id)
    async with async_session_factory() as session2:
        repo = CampaignRepository(session2)
        campaign = await repo.get(campaign_id)
    status = campaign.status if campaign else CampaignStatus.STOPPED
    await callback.message.edit_text(text, reply_markup=campaign_view_kb(cid, status))
    await callback.answer()


# ── Delete ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("campaign:delete:"))
async def cb_campaign_delete(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    campaign_id = callback.data.split(":", 2)[2]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Удалить", callback_data=f"campaign:delete:confirm:{campaign_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"campaign:view:{campaign_id}"),
        ]
    ])
    await callback.message.edit_text(
        "🗑 <b>Удалить кампанию?</b>\n\nВсе логи и настройки будут удалены.",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("campaign:delete:confirm:"))
async def cb_campaign_delete_confirm(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    campaign_id = callback.data.split(":", 3)[3]
    async with async_session_factory() as session:
        async with session.begin():
            repo = CampaignRepository(session)
            await repo.delete(uuid.UUID(campaign_id))
    await callback.message.edit_text("✅ Кампания удалена.", reply_markup=back_kb("menu:campaigns"))
    await callback.answer()
