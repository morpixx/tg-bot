from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db.models import UserSettings


def global_settings_kb(cfg: UserSettings) -> InlineKeyboardMarkup:
    rand = f"{'✅' if cfg.randomize_delay else '❌'} Рандом задержки ({cfg.randomize_min}–{cfg.randomize_max} с)"
    shuffle = f"{'✅' if cfg.shuffle_after_cycle else '❌'} Перемешивать список"
    mode = "📤 Режим: Форвард" if cfg.forward_mode else "📋 Режим: Копия"
    max_c = str(cfg.max_cycles) if cfg.max_cycles else "∞"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"⏱ Задержка между чатами: {cfg.delay_between_chats} с",
                callback_data="gs:delay_between_chats",
            )],
            [InlineKeyboardButton(text=rand, callback_data="gs:randomize_delay")],
            [InlineKeyboardButton(
                text=f"🔄 Задержка между циклами: {cfg.delay_between_cycles} с",
                callback_data="gs:delay_between_cycles",
            )],
            [InlineKeyboardButton(text=shuffle, callback_data="gs:shuffle_after_cycle")],
            [InlineKeyboardButton(
                text=f"🔁 Макс. циклов: {max_c}",
                callback_data="gs:max_cycles",
            )],
            [InlineKeyboardButton(text=mode, callback_data="gs:forward_mode")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")],
        ]
    )
