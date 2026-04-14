from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.utils import back_button
from db.models import Campaign, CampaignSettings, CampaignStatus

_STATUS_EMOJI = {
    CampaignStatus.DRAFT: "📋",
    CampaignStatus.ACTIVE: "▶️",
    CampaignStatus.PAUSED: "⏸",
    CampaignStatus.STOPPED: "⏹",
    CampaignStatus.COMPLETED: "✅",
}


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

    rows.append([InlineKeyboardButton(text="📈 Статистика", callback_data=f"campaign:stats:{campaign_id}")])
    rows.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"campaign:delete:{campaign_id}")])
    rows.append([back_button("menu:campaigns")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def campaign_settings_kb(campaign_id: str, cfg: CampaignSettings) -> InlineKeyboardMarkup:
    """Keyboard showing current values; booleans toggle inline."""
    rand = "✅ Рандом" if cfg.randomize_delay else "❌ Рандом"
    rand += f" ({cfg.randomize_min}–{cfg.randomize_max} с)"
    shuffle = "✅ Перемешивать" if cfg.shuffle_after_cycle else "❌ Перемешивать"
    mode = "📤 Форвард" if cfg.forward_mode else "📋 Копия"
    max_c = str(cfg.max_cycles) if cfg.max_cycles else "∞"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"⏱ Задержка: {cfg.delay_between_chats} с",
                callback_data=f"csetting:delay_between_chats:{campaign_id}",
            )],
            [InlineKeyboardButton(text=rand, callback_data=f"csetting:randomize_delay:{campaign_id}")],
            [InlineKeyboardButton(
                text=f"⏱ Рандом мин: {cfg.randomize_min} с",
                callback_data=f"csetting:randomize_min:{campaign_id}",
            )],
            [InlineKeyboardButton(
                text=f"⏱ Рандом макс: {cfg.randomize_max} с",
                callback_data=f"csetting:randomize_max:{campaign_id}",
            )],
            [InlineKeyboardButton(text=shuffle, callback_data=f"csetting:shuffle_after_cycle:{campaign_id}")],
            [InlineKeyboardButton(
                text=f"🔄 Между циклами: {cfg.delay_between_cycles} с",
                callback_data=f"csetting:delay_between_cycles:{campaign_id}",
            )],
            [InlineKeyboardButton(
                text=f"🔁 Макс. циклов: {max_c}",
                callback_data=f"csetting:max_cycles:{campaign_id}",
            )],
            [InlineKeyboardButton(text=mode, callback_data=f"csetting:forward_mode:{campaign_id}")],
            [back_button(f"campaign:view:{campaign_id}")],
        ]
    )


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
