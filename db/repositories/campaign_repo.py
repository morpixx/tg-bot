from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import (
    Campaign,
    CampaignChat,
    CampaignSession,
    CampaignSettings,
    CampaignStatus,
)


class CampaignRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, campaign_id: uuid.UUID, load_relations: bool = False) -> Campaign | None:
        if not load_relations:
            return await self._session.get(Campaign, campaign_id)
        result = await self._session.execute(
            select(Campaign)
            .where(Campaign.id == campaign_id)
            .options(
                selectinload(Campaign.settings),
                selectinload(Campaign.campaign_sessions).selectinload(CampaignSession.session),
                selectinload(Campaign.campaign_chats).selectinload(CampaignChat.chat),
                selectinload(Campaign.post),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_user(self, user_id: int) -> list[Campaign]:
        result = await self._session.execute(
            select(Campaign)
            .where(Campaign.user_id == user_id)
            .order_by(Campaign.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_active(self) -> list[Campaign]:
        """All active campaigns across all users (for worker)."""
        result = await self._session.execute(
            select(Campaign)
            .where(Campaign.status == CampaignStatus.ACTIVE)
            .options(
                selectinload(Campaign.settings),
                selectinload(Campaign.campaign_sessions).selectinload(CampaignSession.session),
                selectinload(Campaign.campaign_chats).selectinload(CampaignChat.chat),
                selectinload(Campaign.post),
            )
        )
        return list(result.scalars().all())

    async def create(
        self,
        user_id: int,
        name: str,
        post_id: uuid.UUID,
        defaults: dict[str, object] | None = None,
    ) -> Campaign:
        campaign = Campaign(user_id=user_id, name=name, post_id=post_id)
        settings_kwargs = defaults or {}
        settings = CampaignSettings(campaign=campaign, **settings_kwargs)
        self._session.add(campaign)
        self._session.add(settings)
        await self._session.flush()
        return campaign

    async def update_status(self, campaign_id: uuid.UUID, status: CampaignStatus) -> None:
        campaign = await self.get(campaign_id)
        if campaign:
            campaign.status = status
            await self._session.flush()

    async def update_settings(self, campaign_id: uuid.UUID, **kwargs: object) -> None:
        result = await self._session.execute(
            select(CampaignSettings).where(CampaignSettings.campaign_id == campaign_id)
        )
        cfg = result.scalar_one_or_none()
        if cfg:
            for key, val in kwargs.items():
                setattr(cfg, key, val)
            await self._session.flush()

    async def set_sessions(
        self, campaign_id: uuid.UUID, session_offsets: dict[uuid.UUID, int]
    ) -> None:
        """Replace session list for campaign. session_offsets: {session_id: offset_seconds}"""
        result = await self._session.execute(
            select(CampaignSession).where(CampaignSession.campaign_id == campaign_id)
        )
        for cs in result.scalars():
            await self._session.delete(cs)
        for session_id, offset in session_offsets.items():
            self._session.add(
                CampaignSession(
                    campaign_id=campaign_id,
                    session_id=session_id,
                    delay_offset_seconds=offset,
                )
            )
        await self._session.flush()

    async def set_chats(
        self, campaign_id: uuid.UUID, chat_ids: list[uuid.UUID]
    ) -> None:
        """Replace chat list for campaign."""
        result = await self._session.execute(
            select(CampaignChat).where(CampaignChat.campaign_id == campaign_id)
        )
        for cc in result.scalars():
            await self._session.delete(cc)
        for pos, chat_id in enumerate(chat_ids):
            self._session.add(
                CampaignChat(
                    campaign_id=campaign_id,
                    chat_id=chat_id,
                    position=pos,
                )
            )
        await self._session.flush()

    async def increment_cycle(self, campaign_id: uuid.UUID) -> None:
        campaign = await self.get(campaign_id)
        if campaign:
            campaign.current_cycle += 1
            await self._session.flush()

    async def update_session_offset(
        self, campaign_id: uuid.UUID, session_id: uuid.UUID, offset: int
    ) -> None:
        """Update offset for specific session in campaign."""
        result = await self._session.execute(
            select(CampaignSession).where(
                CampaignSession.campaign_id == campaign_id,
                CampaignSession.session_id == session_id,
            )
        )
        cs = result.scalar_one_or_none()
        if cs:
            cs.delay_offset_seconds = offset
            await self._session.flush()

    async def clone(self, campaign_id: uuid.UUID, new_name: str) -> Campaign | None:
        """Duplicate a campaign: settings, session offsets, chats. Status starts as DRAFT."""
        source = await self.get(campaign_id, load_relations=True)
        if source is None:
            return None

        new_campaign = Campaign(
            user_id=source.user_id,
            name=new_name,
            post_id=source.post_id,
            status=CampaignStatus.DRAFT,
        )
        self._session.add(new_campaign)
        await self._session.flush()

        if source.settings:
            src = source.settings
            self._session.add(CampaignSettings(
                campaign_id=new_campaign.id,
                delay_between_chats=src.delay_between_chats,
                randomize_delay=src.randomize_delay,
                randomize_min=src.randomize_min,
                randomize_max=src.randomize_max,
                shuffle_after_cycle=src.shuffle_after_cycle,
                delay_between_cycles=src.delay_between_cycles,
                cycle_delay_randomize=src.cycle_delay_randomize,
                cycle_delay_min=src.cycle_delay_min,
                cycle_delay_max=src.cycle_delay_max,
                max_cycles=src.max_cycles,
                forward_mode=src.forward_mode,
            ))

        for cs in source.campaign_sessions:
            self._session.add(CampaignSession(
                campaign_id=new_campaign.id,
                session_id=cs.session_id,
                delay_offset_seconds=cs.delay_offset_seconds,
            ))

        for cc in source.campaign_chats:
            self._session.add(CampaignChat(
                campaign_id=new_campaign.id,
                chat_id=cc.chat_id,
                position=cc.position,
            ))

        await self._session.flush()
        return new_campaign

    async def delete(self, campaign_id: uuid.UUID) -> None:
        campaign = await self.get(campaign_id)
        if campaign:
            await self._session.delete(campaign)
            await self._session.flush()
