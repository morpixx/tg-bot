from __future__ import annotations

import uuid
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

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

# Fields that toggle inline (no text input needed)
_TOGGLE_FIELDS = {"randomize_delay", "shuffle_after_cycle", "forward_mode"}

_SETTING_PROMPTS: dict[str, str] = {
    "delay_between_chats": "⏱ Введи задержку между чатами в секундах (например: <code>5</code>):",
    "randomize_min": "🎲 Введи минимальную задержку рандома в секундах (например: <code>3</code>):",
    "randomize_max": "🎲 Введи максимальную задержку рандома в секундах (например: <code>10</code>):",
    "delay_between_cycles": "🔄 Введи задержку между циклами в секундах (например: <code>60</code>):",
    "max_cycles": "🔁 Введи максимальное число циклов (0 = бесконечно):",
}


# ── List ──────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:campaigns")
async def cb_campaigns_list(callback: CallbackQuery, db_user: User) -> None:
    assert callback.message
    async with async_session_factory() as session:
        repo = CampaignRepository(session)
        campaigns = await repo.get_by_user(db_user.tg_id)

    active = sum(1 for c in campaigns if c.status == CampaignStatus.ACTIVE)
    header = f"📢 <b>Кампании</b> ({len(campaigns)})"
    if active:
        header += f" · <b>{active} активных</b>"

    await callback.message.edit_text(
        header + "\n\nВыбери кампанию или создай новую:",
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
    cfg = campaign.settings

    status_label = {
        CampaignStatus.DRAFT: "📋 Черновик",
        CampaignStatus.ACTIVE: "▶️ Активна",
        CampaignStatus.PAUSED: "⏸ Пауза",
        CampaignStatus.STOPPED: "⏹ Остановлена",
        CampaignStatus.COMPLETED: "✅ Завершена",
    }.get(campaign.status, "❓")

    mode = "📤 Форвард" if cfg.forward_mode else "📋 Копия"
    rand_info = f"рандом {cfg.randomize_min}–{cfg.randomize_max} с" if cfg.randomize_delay else f"{cfg.delay_between_chats} с"
    max_c = str(cfg.max_cycles) if cfg.max_cycles else "∞"

    text = (
        f"📢 <b>{campaign.name}</b>\n\n"
        f"Статус: {status_label}\n"
        f"Пост: <b>{campaign.post.title if campaign.post else '—'}</b>\n"
        f"Сессий: {sessions_count}  |  Чатов: {chats_count}\n"
        f"Цикл: {campaign.current_cycle} / {max_c}\n\n"
        f"<i>⏱ {rand_info} · {mode} · 🔄 {cfg.delay_between_cycles} с между циклами</i>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=campaign_view_kb(campaign_id, campaign.status),
    )
    await callback.answer()


# ── Create campaign wizard ─────────────────────────────────────────────────────

@router.callback_query(F.data == "campaign:create")
async def cb_campaign_create(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    assert callback.message
    await state.clear()
    await callback.message.edit_text(
        "📢 <b>Новая кампания</b>\n\nШаг 1 из 4: введи название кампании:"
    )
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
        "📝 <b>Шаг 2 из 4: выбери пост для рассылки:</b>",
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
        "📱 <b>Шаг 3 из 4: выбери сессии для рассылки</b>\n\n"
        "Можно выбрать несколько. 💎 = Premium аккаунт.",
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
        "💬 <b>Шаг 4 из 4: выбери чаты для рассылки</b>",
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
    await callback.answer(f"Выбраны все чаты ({len(all_ids)})")


@router.callback_query(F.data == "csel:chats:none", CampaignCreate.waiting_chats)
async def fsm_deselect_all_chats(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    await state.update_data(selected_chats=[])
    async with async_session_factory() as session:
        repo = ChatRepository(session)
        chats = await repo.get_by_user(db_user.tg_id)
    assert callback.message
    await callback.message.edit_reply_markup(reply_markup=chat_select_kb(chats, set()))
    await callback.answer("Выбор снят")


@router.callback_query(F.data == "csel:chats:done", CampaignCreate.waiting_chats)
async def fsm_chats_done(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    assert callback.message
    data = await state.get_data()
    if not data.get("selected_chats"):
        await callback.answer("Выбери хотя бы один чат!", show_alert=True)
        return

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
            await repo.set_sessions(
                campaign.id,
                {uuid.UUID(sid): 0 for sid in data["selected_sessions"]},
            )
            await repo.set_chats(campaign.id, [uuid.UUID(cid) for cid in data["selected_chats"]])
            campaign_id = str(campaign.id)

    await state.clear()
    n_sessions = len(data["selected_sessions"])
    n_chats = len(data["selected_chats"])
    await callback.message.edit_text(
        f"✅ <b>Кампания создана!</b>\n\n"
        f"📢 {data['campaign_name']}\n"
        f"📱 Сессий: {n_sessions}  |  💬 Чатов: {n_chats}\n\n"
        "Настрой параметры или сразу запускай.",
        reply_markup=campaign_view_kb(campaign_id, CampaignStatus.DRAFT),
    )
    await callback.answer()


# ── Settings (inline toggles + numeric input) ─────────────────────────────────

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
    await callback.message.edit_text(
        f"⚙️ <b>Настройки кампании</b> · <i>{campaign.name}</i>\n\n"
        "Нажми кнопку чтобы изменить значение:",
        reply_markup=campaign_settings_kb(campaign_id, cfg),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("csetting:"))
async def cb_setting_edit(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.data and callback.message
    parts = callback.data.split(":")
    field = parts[1]
    campaign_id = parts[2]

    # Toggle booleans inline
    if field in _TOGGLE_FIELDS:
        async with async_session_factory() as session:
            async with session.begin():
                repo = CampaignRepository(session)
                campaign = await repo.get(uuid.UUID(campaign_id), load_relations=True)
                if campaign and campaign.settings:
                    current = getattr(campaign.settings, field)
                    await repo.update_settings(uuid.UUID(campaign_id), **{field: not current})
                    campaign = await repo.get(uuid.UUID(campaign_id), load_relations=True)
        if campaign and campaign.settings:
            await callback.message.edit_reply_markup(
                reply_markup=campaign_settings_kb(campaign_id, campaign.settings)
            )
        await callback.answer("Сохранено")
        return

    prompt = _SETTING_PROMPTS.get(field, "Введи значение:")
    await state.update_data(setting_field=field, setting_campaign_id=campaign_id)
    await callback.message.edit_text(prompt)
    await state.set_state(CampaignSettingsEdit.waiting_value)
    await callback.answer()


@router.message(CampaignSettingsEdit.waiting_value)
async def fsm_setting_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field = data["setting_field"]
    campaign_id = uuid.UUID(data["setting_campaign_id"])
    raw = (message.text or "").strip()

    try:
        if field in ("delay_between_chats", "delay_between_cycles", "randomize_min", "randomize_max"):
            value: object = int(raw)
            if int(raw) < 0:
                raise ValueError
        elif field == "max_cycles":
            value = int(raw) or None
        else:
            value = raw
    except (ValueError, KeyError):
        await message.answer("⚠️ Неверный формат. Введи число:")
        return

    async with async_session_factory() as session:
        async with session.begin():
            repo = CampaignRepository(session)
            await repo.update_settings(campaign_id, **{field: value})
            campaign = await repo.get(campaign_id, load_relations=True)

    await state.clear()
    if campaign and campaign.settings:
        await message.answer(
            "✅ Настройка сохранена.",
            reply_markup=campaign_settings_kb(str(campaign_id), campaign.settings),
        )
    else:
        await message.answer("✅ Настройка сохранена.", reply_markup=back_kb(f"campaign:view:{campaign_id}"))


# ── Control ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("campaign:start:"))
async def cb_campaign_start(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    campaign_id = callback.data.split(":", 2)[2]
    async with async_session_factory() as session:
        async with session.begin():
            repo = CampaignRepository(session)
            campaign = await repo.get(uuid.UUID(campaign_id))
            if campaign:
                campaign.status = CampaignStatus.ACTIVE
                campaign.started_at = datetime.now(timezone.utc)
    await callback.message.edit_text(
        "▶️ <b>Кампания запущена!</b>\n\nВоркер начнёт рассылку в течение 10 секунд.",
        reply_markup=campaign_view_kb(campaign_id, CampaignStatus.ACTIVE),
    )
    await callback.answer("Запущено!")


@router.callback_query(F.data.startswith("campaign:pause:"))
async def cb_campaign_pause(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    campaign_id = callback.data.split(":", 2)[2]
    async with async_session_factory() as session:
        async with session.begin():
            repo = CampaignRepository(session)
            await repo.update_status(uuid.UUID(campaign_id), CampaignStatus.PAUSED)
    await callback.message.edit_text(
        "⏸ <b>Кампания приостановлена.</b>\n\nВоркер завершит текущий чат и встанет на паузу.",
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


@router.callback_query(F.data.startswith("campaign:restart:"))
async def cb_campaign_restart(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    campaign_id = callback.data.split(":", 2)[2]
    async with async_session_factory() as session:
        async with session.begin():
            repo = CampaignRepository(session)
            campaign = await repo.get(uuid.UUID(campaign_id))
            if campaign:
                campaign.status = CampaignStatus.ACTIVE
                campaign.current_cycle = 0
                campaign.started_at = datetime.now(timezone.utc)
    await callback.message.edit_text(
        "🔄 <b>Кампания перезапущена с нуля!</b>",
        reply_markup=campaign_view_kb(campaign_id, CampaignStatus.ACTIVE),
    )
    await callback.answer("Перезапущено!")


# ── Test send ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("campaign:test:"))
async def cb_campaign_test(callback: CallbackQuery, db_user: User) -> None:
    assert callback.message and callback.data and callback.bot
    campaign_id = callback.data.split(":", 2)[2]

    async with async_session_factory() as session:
        repo = CampaignRepository(session)
        campaign = await repo.get(uuid.UUID(campaign_id), load_relations=True)

    if not campaign:
        await callback.answer("Кампания не найдена", show_alert=True)
        return
    if not campaign.campaign_sessions:
        await callback.answer("Нет сессий в кампании", show_alert=True)
        return

    # Use first active session to send to the user's own chat
    from worker.session_pool import SessionPool
    from worker.broadcaster import Broadcaster
    from services.crypto import decrypt
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from bot.core.config import settings as cfg

    await callback.answer("⏳ Отправляю тестовое сообщение...")

    tg_session = campaign.campaign_sessions[0].session
    try:
        plain = decrypt(tg_session.encrypted_session)
        client = TelegramClient(
            StringSession(plain),
            cfg.telethon_api_id,
            cfg.telethon_api_hash,
            device_model="iPhone 14 Pro Max",
            system_version="16.0",
            app_version="9.6.3",
        )
        await client.connect()
        if not await client.is_user_authorized():
            await callback.bot.send_message(db_user.tg_id, "❌ Сессия не авторизована.")
            await client.disconnect()
            return

        broadcaster = Broadcaster(SessionPool())
        status, msg_id, error = await broadcaster._send_post(
            client=client,
            post=campaign.post,
            chat_id=db_user.tg_id,
            forward_mode=campaign.settings.forward_mode,
        )
        await client.disconnect()

        if status.value == "success":
            await callback.bot.send_message(
                db_user.tg_id,
                f"✅ <b>Тест прошёл успешно!</b> Сообщение выше — это твой пост как он будет выглядеть.",
            )
        else:
            await callback.bot.send_message(
                db_user.tg_id,
                f"❌ Ошибка тестовой отправки: {error}",
            )
    except Exception as e:
        await callback.bot.send_message(db_user.tg_id, f"❌ Ошибка: {e}")


# ── Progress ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("campaign:progress:"))
async def cb_campaign_progress(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    campaign_id_str = callback.data.split(":", 2)[2]
    campaign_id = uuid.UUID(campaign_id_str)

    from worker.broadcaster import get_progress
    sent, total = get_progress(campaign_id)

    async with async_session_factory() as session:
        repo = CampaignRepository(session)
        campaign = await repo.get(campaign_id)

    if not campaign:
        await callback.answer("Кампания не найдена", show_alert=True)
        return

    if total == 0:
        progress_bar = "нет данных"
        pct = 0
    else:
        pct = int(sent / total * 100)
        filled = pct // 10
        progress_bar = "█" * filled + "░" * (10 - filled) + f" {pct}%"

    text = (
        f"📡 <b>Прогресс кампании</b>\n\n"
        f"Цикл: <b>{campaign.current_cycle}</b>\n"
        f"Отправлено: <b>{sent}</b> / {total}\n"
        f"{progress_bar}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"campaign:progress:{campaign_id_str}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"campaign:view:{campaign_id_str}")],
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


# ── Stats ──────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("campaign:stats:"))
async def cb_campaign_stats(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    from sqlalchemy import func, select
    from db.models import BroadcastLog, BroadcastStatus

    campaign_id = uuid.UUID(callback.data.split(":", 2)[2])
    async with async_session_factory() as session:
        result = await session.execute(
            select(BroadcastLog.status, func.count())
            .where(BroadcastLog.campaign_id == campaign_id)
            .group_by(BroadcastLog.status)
        )
        stats = dict(result.all())

        # Last 5 errors
        last_errors_result = await session.execute(
            select(BroadcastLog.error, BroadcastLog.chat_id)
            .where(
                BroadcastLog.campaign_id == campaign_id,
                BroadcastLog.status == BroadcastStatus.FAILED,
                BroadcastLog.error.isnot(None),
            )
            .order_by(BroadcastLog.sent_at.desc())
            .limit(3)
        )
        last_errors = last_errors_result.all()

    success = stats.get(BroadcastStatus.SUCCESS, 0)
    failed = stats.get(BroadcastStatus.FAILED, 0)
    flood = stats.get(BroadcastStatus.FLOOD_WAIT, 0)
    skipped = stats.get(BroadcastStatus.SKIPPED, 0)
    total = success + failed + flood + skipped
    sr = f"{int(success/total*100)}%" if total else "—"

    text = (
        f"📈 <b>Статистика кампании</b>\n\n"
        f"✅ Успешно: <b>{success}</b>\n"
        f"❌ Ошибок: {failed}\n"
        f"⏳ FloodWait: {flood}\n"
        f"⏭ Пропущено: {skipped}\n"
        f"📊 Всего: {total}  |  SR: {sr}"
    )
    if last_errors:
        text += "\n\n<i>Последние ошибки:</i>"
        for err, chat_id in last_errors:
            text += f"\n• <code>{chat_id}</code>: {(err or '')[:60]}"

    cid = str(campaign_id)
    async with async_session_factory() as session2:
        repo = CampaignRepository(session2)
        campaign = await repo.get(campaign_id)
    status = campaign.status if campaign else CampaignStatus.STOPPED
    await callback.message.edit_text(text, reply_markup=campaign_view_kb(cid, status))
    await callback.answer()


# ── Edit campaign (change post/sessions/chats after creation) ─────────────────

@router.callback_query(F.data.startswith("campaign:edit:"))
async def cb_campaign_edit(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    campaign_id = callback.data.split(":", 2)[2]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Сменить пост", callback_data=f"campaign:edit:post:{campaign_id}")],
        [InlineKeyboardButton(text="📱 Сменить сессии", callback_data=f"campaign:edit:sessions:{campaign_id}")],
        [InlineKeyboardButton(text="💬 Сменить чаты", callback_data=f"campaign:edit:chats:{campaign_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"campaign:view:{campaign_id}")],
    ])
    await callback.message.edit_text(
        "✏️ <b>Редактировать кампанию</b>\n\nЧто изменить?",
        reply_markup=kb,
    )
    await callback.answer()


# ── Delete ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("campaign:delete:") & ~F.data.startswith("campaign:delete:confirm:"))
async def cb_campaign_delete(callback: CallbackQuery) -> None:
    assert callback.message and callback.data
    campaign_id = callback.data.split(":", 2)[2]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Удалить", callback_data=f"campaign:delete:confirm:{campaign_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"campaign:view:{campaign_id}"),
        ]
    ])
    await callback.message.edit_text(
        "🗑 <b>Удалить кампанию?</b>\n\nВсе логи и настройки будут удалены безвозвратно.",
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
