from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.utils import back_button
from db.models import Campaign, CampaignStatus


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
        rows.append([InlineKeyboardButton(text=f"{emoji} {c.name}", callback_data=f"campaign:view:{c.id}")])
    rows.append([InlineKeyboardButton(text="➕ Новая кампания", callback_data="campaign:create")])
    rows.append([back_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def campaign_view_kb(campaign_id: str, status: CampaignStatus) -> InlineKeyboardMarkup:
    rows = []
    if status == CampaignStatus.DRAFT:
        rows.append([InlineKeyboardButton(text="▶️ Запустить", callback_data=f"campaign:start:{campaign_id}")])
        rows.append([InlineKeyboardButton(text="✉️ Тестовая отправка", callback_data=f"campaign:test:{campaign_id}")])
        rows.append([InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"campaign:settings:{campaign_id}")])
    elif status == CampaignStatus.ACTIVE:
        rows.append([
            InlineKeyboardButton(text="⏸ Пауза", callback_data=f"campaign:pause:{campaign_id}"),
            InlineKeyboardButton(text="⏹ Стоп", callback_data=f"campaign:stop:{campaign_id}"),
        ])
        rows.append([InlineKeyboardButton(text="📊 Прогресс", callback_data=f"campaign:progress:{campaign_id}")])
    elif status == CampaignStatus.PAUSED:
        rows.append([
            InlineKeyboardButton(text="▶️ Возобновить", callback_data=f"campaign:resume:{campaign_id}"),
            InlineKeyboardButton(text="⏹ Стоп", callback_data=f"campaign:stop:{campaign_id}"),
        ])
    rows.append([InlineKeyboardButton(text="📈 Статистика", callback_data=f"campaign:stats:{campaign_id}")])
    rows.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"campaign:delete:{campaign_id}")])
    rows.append([back_button("menu:campaigns")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def campaign_settings_kb(campaign_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏱ Задержка между чатами", callback_data=f"csetting:delay_between_chats:{campaign_id}")],
            [InlineKeyboardButton(text="🎲 Рандомизация задержки", callback_data=f"csetting:randomize_delay:{campaign_id}")],
            [InlineKeyboardButton(text="🔀 Перемешивать список", callback_data=f"csetting:shuffle_after_cycle:{campaign_id}")],
            [InlineKeyboardButton(text="🔄 Задержка между циклами", callback_data=f"csetting:delay_between_cycles:{campaign_id}")],
            [InlineKeyboardButton(text="🔁 Макс. циклов", callback_data=f"csetting:max_cycles:{campaign_id}")],
            [InlineKeyboardButton(text="📤 Режим отправки", callback_data=f"csetting:forward_mode:{campaign_id}")],
            [back_button(f"campaign:view:{campaign_id}")],
        ]
    )


def session_select_kb(sessions: list, selected_ids: set[str]) -> InlineKeyboardMarkup:
    rows = []
    for s in sessions:
        sid = str(s.id)
        check = "✅" if sid in selected_ids else "⬜"
        premium = " 💎" if s.has_premium else ""
        rows.append([InlineKeyboardButton(
            text=f"{check} {s.name}{premium}",
            callback_data=f"csel:session:{sid}",
        )])
    rows.append([InlineKeyboardButton(text="➡️ Далее", callback_data="csel:sessions:done")])
    rows.append([back_button("campaign:create")])
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
    rows.append([InlineKeyboardButton(text="✅ Все", callback_data="csel:chats:all")])
    rows.append([InlineKeyboardButton(text="➡️ Далее", callback_data="csel:chats:done")])
    rows.append([back_button("campaign:create")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
