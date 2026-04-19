from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.utils import back_button
from db.models import Campaign, CampaignSession, CampaignSettings, CampaignStatus

_STATUS_EMOJI = {
    CampaignStatus.DRAFT: "📋",
    CampaignStatus.ACTIVE: "▶️",
    CampaignStatus.PAUSED: "⏸",
    CampaignStatus.STOPPED: "⏹",
    CampaignStatus.COMPLETED: "✅",
}

# Short codes for campaign-settings fields — keeps callback_data under the 64-byte Telegram limit.
SETTING_CODES: dict[str, str] = {
    "delay_between_chats": "dc",
    "randomize_delay": "rd",
    "randomize_min": "rn",
    "randomize_max": "rx",
    "delay_between_cycles": "dy",
    "cycle_delay_randomize": "cr",
    "cycle_delay_min": "cn",
    "cycle_delay_max": "cx",
    "max_cycles": "mc",
    "forward_mode": "fm",
    "shuffle_after_cycle": "sh",
}
SETTING_FIELDS: dict[str, str] = {code: field for field, code in SETTING_CODES.items()}


def campaigns_list_kb(campaigns: list[Campaign]) -> InlineKeyboardMarkup:
    rows = []
    for c in campaigns:
        emoji = _STATUS_EMOJI.get(c.status, "❓")
        rows.append([InlineKeyboardButton(
            text=f"{emoji} {c.name}",
            callback_data=f"campaign:view:{c.id}",
        )])
    rows.append([InlineKeyboardButton(text="➕ Новая кампания", callback_data="campaign:create")])
    rows.append([back_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def campaign_view_kb(campaign_id: str, status: CampaignStatus) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if status == CampaignStatus.DRAFT:
        rows.append([InlineKeyboardButton(text="▶️ Запустить", callback_data=f"campaign:start:{campaign_id}")])
        rows.append([InlineKeyboardButton(text="✉️ Тест (отправить себе)", callback_data=f"campaign:test:{campaign_id}")])
        rows.append([InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"campaign:settings:{campaign_id}")])
        rows.append([InlineKeyboardButton(text="✏️ Изменить", callback_data=f"campaign:edit:{campaign_id}")])

    elif status == CampaignStatus.ACTIVE:
        rows.append([
            InlineKeyboardButton(text="⏸ Пауза", callback_data=f"campaign:pause:{campaign_id}"),
            InlineKeyboardButton(text="⏹ Стоп", callback_data=f"campaign:stop:{campaign_id}"),
        ])
        rows.append([InlineKeyboardButton(text="📡 Прогресс", callback_data=f"campaign:progress:{campaign_id}")])
        rows.append([InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"campaign:settings:{campaign_id}")])

    elif status == CampaignStatus.PAUSED:
        rows.append([
            InlineKeyboardButton(text="▶️ Возобновить", callback_data=f"campaign:resume:{campaign_id}"),
            InlineKeyboardButton(text="⏹ Стоп", callback_data=f"campaign:stop:{campaign_id}"),
        ])
        rows.append([InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"campaign:settings:{campaign_id}")])

    elif status in (CampaignStatus.STOPPED, CampaignStatus.COMPLETED):
        rows.append([InlineKeyboardButton(text="🔄 Перезапустить", callback_data=f"campaign:restart:{campaign_id}")])
        rows.append([InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"campaign:settings:{campaign_id}")])

    rows.append([
        InlineKeyboardButton(text="📈 Статистика", callback_data=f"campaign:stats:{campaign_id}"),
        InlineKeyboardButton(text="⏱ Офсеты", callback_data=f"campaign:offsets:{campaign_id}"),
    ])
    rows.append([
        InlineKeyboardButton(text="📑 Клонировать", callback_data=f"campaign:clone:{campaign_id}"),
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"campaign:delete:{campaign_id}"),
    ])
    rows.append([back_button("menu:campaigns")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def campaign_settings_kb(campaign_id: str, cfg: CampaignSettings) -> InlineKeyboardMarkup:
    """Shows current values; booleans toggle inline."""
    rand = f"{'✅' if cfg.randomize_delay else '❌'} Рандом задержки чатов"
    shuffle = f"{'✅' if cfg.shuffle_after_cycle else '❌'} Перемешивать список"
    mode = "📤 Форвард" if cfg.forward_mode else "📋 Копия"
    max_c = str(cfg.max_cycles) if cfg.max_cycles else "∞"
    cycle_rand = f"{'✅' if cfg.cycle_delay_randomize else '❌'} Рандом между циклами"

    def cb(field: str) -> str:
        return f"cs:{SETTING_CODES[field]}:{campaign_id}"

    rows = [
        # ── Задержка между чатами ──
        [InlineKeyboardButton(
            text=f"⏱ Задержка: {cfg.delay_between_chats} с",
            callback_data=cb("delay_between_chats"),
        )],
        [InlineKeyboardButton(text=rand, callback_data=cb("randomize_delay"))],
    ]

    if cfg.randomize_delay:
        rows.append([InlineKeyboardButton(
            text=f"   ↳ мин: {cfg.randomize_min} с",
            callback_data=cb("randomize_min"),
        )])
        rows.append([InlineKeyboardButton(
            text=f"   ↳ макс: {cfg.randomize_max} с",
            callback_data=cb("randomize_max"),
        )])

    rows += [
        # ── Задержка между циклами ──
        [InlineKeyboardButton(
            text=f"🔄 Между циклами: {cfg.delay_between_cycles} с",
            callback_data=cb("delay_between_cycles"),
        )],
        [InlineKeyboardButton(text=cycle_rand, callback_data=cb("cycle_delay_randomize"))],
    ]

    if cfg.cycle_delay_randomize:
        rows.append([InlineKeyboardButton(
            text=f"   ↳ мин: {cfg.cycle_delay_min} с",
            callback_data=cb("cycle_delay_min"),
        )])
        rows.append([InlineKeyboardButton(
            text=f"   ↳ макс: {cfg.cycle_delay_max} с",
            callback_data=cb("cycle_delay_max"),
        )])

    rows += [
        [InlineKeyboardButton(text=shuffle, callback_data=cb("shuffle_after_cycle"))],
        [InlineKeyboardButton(
            text=f"🔁 Макс. циклов: {max_c}",
            callback_data=cb("max_cycles"),
        )],
        [InlineKeyboardButton(text=mode, callback_data=cb("forward_mode"))],
        [back_button(f"campaign:view:{campaign_id}")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=rows)


def session_offsets_kb(
    campaign_id: str,
    campaign_sessions: list[CampaignSession],
) -> InlineKeyboardMarkup:
    """Shows each session with its current offset; click to edit."""
    rows = []
    for cs in campaign_sessions:
        name = cs.session.name if cs.session else "—"
        premium = " 💎" if cs.session and cs.session.has_premium else ""
        offset_label = f"{cs.delay_offset_seconds} с" if cs.delay_offset_seconds else "сразу"
        rows.append([InlineKeyboardButton(
            text=f"📱 {name}{premium}  →  ⏱ {offset_label}",
            callback_data=f"coe:{cs.session_id}",
        )])
    rows.append([back_button(f"campaign:view:{campaign_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def session_select_kb(sessions: list, selected_ids: set[str]) -> InlineKeyboardMarkup:
    rows = []
    for s in sessions:
        sid = str(s.id)
        check = "✅" if sid in selected_ids else "⬜"
        premium = " 💎" if s.has_premium else ""
        status = "🟢" if s.is_active else "🔴"
        rows.append([InlineKeyboardButton(
            text=f"{check} {status} {s.name}{premium}",
            callback_data=f"csel:session:{sid}",
        )])
    rows.append([InlineKeyboardButton(text="➡️ Далее", callback_data="csel:sessions:done")])
    rows.append([back_button("menu:campaigns")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def chat_select_kb(chats: list, selected_ids: set[str]) -> InlineKeyboardMarkup:
    rows = []
    for c in chats:
        cid = str(c.id)
        check = "✅" if cid in selected_ids else "⬜"
        rows.append([InlineKeyboardButton(
            text=f"{check} {c.title}",
            callback_data=f"csel:chat:{cid}",
        )])
    rows.append([
        InlineKeyboardButton(text="✅ Все", callback_data="csel:chats:all"),
        InlineKeyboardButton(text="☑️ Снять всё", callback_data="csel:chats:none"),
    ])
    rows.append([InlineKeyboardButton(text="➡️ Далее", callback_data="csel:chats:done")])
    rows.append([back_button("menu:campaigns")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
