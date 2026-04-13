from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.keyboards.utils import back_kb
from db.models import BroadcastStatus, CampaignStatus, User
from db.session import async_session_factory

router = Router()


@router.callback_query(F.data == "menu:stats")
async def cb_stats(callback: CallbackQuery, db_user: User) -> None:
    assert callback.message
    from sqlalchemy import func, select
    from db.models import BroadcastLog, Campaign

    async with async_session_factory() as session:
        # Total campaigns
        total_campaigns = (await session.execute(
            select(func.count()).where(Campaign.user_id == db_user.tg_id)
        )).scalar() or 0

        active_campaigns = (await session.execute(
            select(func.count()).where(
                Campaign.user_id == db_user.tg_id,
                Campaign.status == CampaignStatus.ACTIVE,
            )
        )).scalar() or 0

        # Get user's campaign ids
        campaign_ids_result = await session.execute(
            select(Campaign.id).where(Campaign.user_id == db_user.tg_id)
        )
        campaign_ids = [r[0] for r in campaign_ids_result]

        success = failed = 0
        if campaign_ids:
            success = (await session.execute(
                select(func.count()).where(
                    BroadcastLog.campaign_id.in_(campaign_ids),
                    BroadcastLog.status == BroadcastStatus.SUCCESS,
                )
            )).scalar() or 0
            failed = (await session.execute(
                select(func.count()).where(
                    BroadcastLog.campaign_id.in_(campaign_ids),
                    BroadcastLog.status == BroadcastStatus.FAILED,
                )
            )).scalar() or 0

    text = (
        "📊 <b>Общая статистика</b>\n\n"
        f"📢 Кампаний: {total_campaigns} (активных: {active_campaigns})\n"
        f"✅ Успешных отправок: {success}\n"
        f"❌ Ошибок: {failed}\n"
    )
    await callback.message.edit_text(text, reply_markup=back_kb())
    await callback.answer()
