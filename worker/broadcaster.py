from __future__ import annotations

import asyncio
import random
import uuid
from datetime import datetime, timezone

import structlog
from telethon import TelegramClient
from telethon.errors import (
    ChatWriteForbiddenError,
    FloodWaitError,
    UserBannedInChannelError,
)

from db.models import BroadcastStatus, Campaign, CampaignStatus, Post, PostType
from db.repositories.campaign_repo import CampaignRepository
from db.session import async_session_factory
from worker.session_pool import SessionPool

log = structlog.get_logger()

# Per-campaign stop signals
_stop_signals: dict[uuid.UUID, bool] = {}
# Live progress callbacks: campaign_id -> (sent, total)
_progress: dict[uuid.UUID, tuple[int, int]] = {}


def request_stop(campaign_id: uuid.UUID) -> None:
    _stop_signals[campaign_id] = True


def get_progress(campaign_id: uuid.UUID) -> tuple[int, int]:
    return _progress.get(campaign_id, (0, 0))


class Broadcaster:
    def __init__(self, pool: SessionPool) -> None:
        self._pool = pool

    async def run_campaign(self, campaign_id: uuid.UUID) -> None:
        """Main broadcast loop for one campaign. Runs until stopped or max cycles."""
        log.info("Starting campaign", campaign_id=str(campaign_id))
        _stop_signals.pop(campaign_id, None)

        while True:
            if _stop_signals.get(campaign_id):
                log.info("Campaign stop requested", campaign_id=str(campaign_id))
                break

            async with async_session_factory() as session:
                repo = CampaignRepository(session)
                campaign = await repo.get(campaign_id, load_relations=True)

            if not campaign or campaign.status not in (CampaignStatus.ACTIVE, CampaignStatus.PAUSED):
                log.info("Campaign ended or not found", campaign_id=str(campaign_id))
                break

            # Wait while paused
            if campaign.status == CampaignStatus.PAUSED:
                await asyncio.sleep(5)
                continue

            cfg = campaign.settings
            chats = [cc.chat for cc in sorted(campaign.campaign_chats, key=lambda x: x.position)]
            sessions_map = {cs.session_id: (cs.session, cs.delay_offset_seconds) for cs in campaign.campaign_sessions}

            if not chats or not sessions_map:
                log.warning("Campaign has no chats or sessions", campaign_id=str(campaign_id))
                break

            # Shuffle chat list for this cycle if configured
            if cfg.shuffle_after_cycle and campaign.current_cycle > 0:
                random.shuffle(chats)

            total = len(chats) * len(sessions_map)
            sent = 0
            _progress[campaign_id] = (0, total)

            # For each chat, schedule sends per session (with offsets)
            tasks = []
            for tg_session, offset in sessions_map.values():
                tasks.append(self._broadcast_session(
                    campaign=campaign,
                    tg_session=tg_session,
                    chats=chats,
                    offset_seconds=offset,
                    on_sent=lambda: None,  # progress tracked below
                ))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Count successes across all session results
            for r in results:
                if isinstance(r, int):
                    sent += r

            _progress[campaign_id] = (sent, total)
            log.info("Cycle complete", campaign_id=str(campaign_id), cycle=campaign.current_cycle + 1, sent=sent)

            async with async_session_factory() as session:
                async with session.begin():
                    repo = CampaignRepository(session)
                    await repo.increment_cycle(campaign_id)

                    # Check max_cycles
                    updated = await repo.get(campaign_id)
                    if updated and cfg.max_cycles and updated.current_cycle >= cfg.max_cycles:
                        await repo.update_status(campaign_id, CampaignStatus.COMPLETED)
                        log.info("Campaign completed max cycles", campaign_id=str(campaign_id))
                        _progress.pop(campaign_id, None)
                        return

            # Delay between cycles
            delay = cfg.delay_between_cycles
            if cfg.cycle_delay_randomize:
                delay = random.randint(cfg.cycle_delay_min, cfg.cycle_delay_max)
            log.info("Sleeping between cycles", seconds=delay)
            await asyncio.sleep(delay)

        _progress.pop(campaign_id, None)

    async def _broadcast_session(
        self,
        campaign: Campaign,
        tg_session,  # type: ignore[no-untyped-def]
        chats: list,
        offset_seconds: int,
        on_sent,  # type: ignore[no-untyped-def]
    ) -> int:
        """Broadcast to all chats using one session. Returns sent count."""
        if offset_seconds > 0:
            await asyncio.sleep(offset_seconds)

        client = await self._pool.get_or_connect(tg_session)
        if not client:
            log.warning("Could not connect session", session_id=str(tg_session.id))
            return 0

        cfg = campaign.settings
        sent = 0

        for chat in chats:
            if _stop_signals.get(campaign.id):
                break

            # Check paused
            async with async_session_factory() as session:
                repo = CampaignRepository(session)
                c = await repo.get(campaign.id)
                if c and c.status == CampaignStatus.PAUSED:
                    while True:
                        await asyncio.sleep(3)
                        async with async_session_factory() as s2:
                            r2 = CampaignRepository(s2)
                            c2 = await r2.get(campaign.id)
                        if not c2 or c2.status != CampaignStatus.PAUSED:
                            break

            status, message_id, error = await self._send_post(
                client=client,
                post=campaign.post,
                chat_id=chat.chat_id,
                forward_mode=cfg.forward_mode,
            )

            # Log result
            async with async_session_factory() as session:
                async with session.begin():
                    from db.models import BroadcastLog
                    session.add(BroadcastLog(
                        campaign_id=campaign.id,
                        session_id=tg_session.id,
                        chat_id=chat.chat_id,
                        cycle=campaign.current_cycle + 1,
                        message_id=message_id,
                        status=status,
                        error=error,
                    ))

            if status == BroadcastStatus.SUCCESS:
                sent += 1

            # Delay between chats
            delay = cfg.delay_between_chats
            if cfg.randomize_delay:
                delay = random.randint(cfg.randomize_min, cfg.randomize_max)
            await asyncio.sleep(delay)

        return sent

    async def _send_post(
        self,
        client: TelegramClient,
        post: Post,
        chat_id: int,
        forward_mode: bool,
    ) -> tuple[BroadcastStatus, int | None, str | None]:
        try:
            if post.type == PostType.FORWARDED and forward_mode:
                result = await client.forward_messages(
                    entity=chat_id,
                    messages=post.source_message_id,
                    from_peer=post.source_chat_id,
                )
                msg_id = result[0].id if result else None
            elif post.type == PostType.FORWARDED and not forward_mode:
                # Copy without attribution
                msg = await client.get_messages(post.source_chat_id, ids=post.source_message_id)
                if not msg:
                    return BroadcastStatus.SKIPPED, None, "Source message not found"
                result = await client.send_message(
                    entity=chat_id,
                    message=msg.message or "",
                    file=msg.media if msg.media else None,
                    formatting_entities=msg.entities,
                )
                msg_id = result.id
            elif post.type in (PostType.PHOTO, PostType.VIDEO, PostType.DOCUMENT):
                import json
                entities = None
                if post.text_entities:
                    from telethon.tl.types import MessageEntity
                    raw = json.loads(post.text_entities)
                    entities = [MessageEntity(**e) for e in raw] if raw else None
                result = await client.send_file(
                    entity=chat_id,
                    file=post.media_file_id,
                    caption=post.text or "",
                    formatting_entities=entities,
                )
                msg_id = result.id
            else:
                # Text
                import json
                entities = None
                if post.text_entities:
                    from telethon.tl.types import MessageEntity
                    raw = json.loads(post.text_entities)
                    entities = [MessageEntity(**e) for e in raw] if raw else None
                result = await client.send_message(
                    entity=chat_id,
                    message=post.text or "",
                    formatting_entities=entities,
                )
                msg_id = result.id

            return BroadcastStatus.SUCCESS, msg_id, None

        except FloodWaitError as e:
            log.warning("FloodWait", chat_id=chat_id, seconds=e.seconds)
            await asyncio.sleep(e.seconds + 5)
            return BroadcastStatus.FLOOD_WAIT, None, f"FloodWait {e.seconds}s"

        except (ChatWriteForbiddenError, UserBannedInChannelError) as e:
            log.warning("Cannot write to chat", chat_id=chat_id, error=str(e))
            return BroadcastStatus.SKIPPED, None, str(e)

        except Exception as e:
            log.error("Send error", chat_id=chat_id, error=str(e))
            return BroadcastStatus.FAILED, None, str(e)
