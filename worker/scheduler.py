from __future__ import annotations

import asyncio
import uuid

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.core.config import settings
from db.repositories.campaign_repo import CampaignRepository
from db.repositories.session_repo import SessionRepository
from db.session import async_session_factory
from worker.broadcaster import Broadcaster
from worker.session_pool import SessionPool

log = structlog.get_logger()


class WorkerScheduler:
    def __init__(self) -> None:
        self._pool = SessionPool()
        self._broadcaster = Broadcaster(self._pool)
        self._scheduler = AsyncIOScheduler()
        self._running_campaigns: dict[uuid.UUID, asyncio.Task] = {}  # type: ignore[type-arg]

    def start(self) -> None:
        self._scheduler.add_job(
            self._poll_campaigns,
            "interval",
            seconds=10,
            id="poll_campaigns",
        )
        self._scheduler.add_job(
            self._health_check_sessions,
            "interval",
            seconds=settings.session_health_check_interval,
            id="health_check",
        )
        self._scheduler.start()
        log.info("WorkerScheduler started")

    async def _poll_campaigns(self) -> None:
        """Check for new active campaigns and start/stop broadcast tasks."""
        async with async_session_factory() as session:
            repo = CampaignRepository(session)
            active = await repo.get_active()

        active_ids = {c.id for c in active}

        # Start tasks for newly active campaigns
        for campaign in active:
            if campaign.id not in self._running_campaigns:
                log.info("Launching campaign task", campaign_id=str(campaign.id))
                self._launch(campaign.id)

        # Remove finished tasks for campaigns no longer active
        for cid in list(self._running_campaigns.keys()):
            if cid not in active_ids:
                task = self._running_campaigns.get(cid)
                if task and not task.done():
                    from worker.broadcaster import request_stop
                    request_stop(cid)

    def _launch(self, cid: uuid.UUID) -> None:
        task = asyncio.create_task(
            self._broadcaster.run_campaign(cid),
            name=f"campaign-{cid}",
        )
        self._running_campaigns[cid] = task
        task.add_done_callback(lambda t: self._on_campaign_done(cid, t))

    def _on_campaign_done(self, campaign_id: uuid.UUID, task: asyncio.Task) -> None:  # type: ignore[type-arg]
        self._running_campaigns.pop(campaign_id, None)
        if task.exception():
            log.error("Campaign task failed", campaign_id=str(campaign_id), error=str(task.exception()))
        else:
            log.info("Campaign task finished", campaign_id=str(campaign_id))

    async def _health_check_sessions(self) -> None:
        """Check all active sessions are still valid (runs in parallel)."""
        from bot.core.bot import bot
        async with async_session_factory() as session:
            repo = SessionRepository(session)
            sessions = await repo.get_all_active()

        async def _check_one(tg_session) -> None:  # type: ignore[no-untyped-def]
            alive = await self._pool.health_check(tg_session)
            if not alive:
                log.warning("Session dead", session_id=str(tg_session.id), name=tg_session.name)
                try:
                    await bot.send_message(
                        tg_session.user_id,
                        f"⚠️ Сессия <b>{tg_session.name}</b> отключилась. Необходимо переавторизоваться.",
                    )
                except Exception:
                    pass
                async with async_session_factory() as db_session:
                    async with db_session.begin():
                        repo2 = SessionRepository(db_session)
                        await repo2.update(tg_session.id, is_active=False)

        if sessions:
            await asyncio.gather(*[_check_one(s) for s in sessions], return_exceptions=True)

    async def shutdown(self) -> None:
        self._scheduler.shutdown()
        for task in self._running_campaigns.values():
            task.cancel()
        await self._pool.disconnect_all()
