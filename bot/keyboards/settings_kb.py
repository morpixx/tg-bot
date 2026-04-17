from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db.models import UserSettings


def global_settings_kb(cfg: UserSettings) -> InlineKeyboardMarkup:
    rand = f"{'✅' if cfg.randomize_delay else '❌'} Рандом задержки чатов"
    shuffle = f"{'✅' if cfg.shuffle_after_cycle else '❌'} Перемешивать список"
    mode = "📤 Режим: Форвард" if cfg.forward_mode else "📋 Режим: Копия"
    max_c = str(cfg.max_cycles) if cfg.max_cycles else "∞"
    cycle_rand = f"{'✅' if cfg.cycle_delay_randomize else '❌'} Рандом между циклами"

    rows = [
        # ── Задержка между чатами ──
        [InlineKeyboardButton(
            text=f"⏱ Задержка между чатами: {cfg.delay_between_chats} с",
            callback_data="gs:delay_between_chats",
        )],
        [InlineKeyboardButton(text=rand, callback_data="gs:randomize_delay")],
    ]

    # Показываем min/max только если рандом включён
    if cfg.randomize_delay:
        rows.append([InlineKeyboardButton(
            text=f"   ↳ мин: {cfg.randomize_min} с",
            callback_data="gs:randomize_min",
        )])
        rows.append([InlineKeyboardButton(
            text=f"   ↳ макс: {cfg.randomize_max} с",
            callback_data="gs:randomize_max",
        )])

    rows += [
        # ── Задержка между циклами ──
        [InlineKeyboardButton(
            text=f"🔄 Задержка между циклами: {cfg.delay_between_cycles} с",
            callback_data="gs:delay_between_cycles",
        )],
        [InlineKeyboardButton(text=cycle_rand, callback_data="gs:cycle_delay_randomize")],
    ]

    if cfg.cycle_delay_randomize:
        rows.append([InlineKeyboardButton(
            text=f"   ↳ мин: {cfg.cycle_delay_min} с",
            callback_data="gs:cycle_delay_min",
        )])
        rows.append([InlineKeyboardButton(
            text=f"   ↳ макс: {cfg.cycle_delay_max} с",
            callback_data="gs:cycle_delay_max",
        )])

    rows += [
        [InlineKeyboardButton(text=shuffle, callback_data="gs:shuffle_after_cycle")],
        [InlineKeyboardButton(
            text=f"🔁 Макс. циклов: {max_c}",
            callback_data="gs:max_cycles",
        )],
        [InlineKeyboardButton(text=mode, callback_data="gs:forward_mode")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=rows)
