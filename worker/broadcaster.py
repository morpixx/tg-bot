from __future__ import annotations

import asyncio
import io
import json
import random
import uuid

import structlog
from opentele2.tl import TelegramClient
from telethon import tl
from telethon.errors import (
    ChatWriteForbiddenError,
    FloodWaitError,
    UserBannedInChannelError,
)

from db.models import BroadcastLog, BroadcastStatus, Campaign, CampaignStatus, Post, PostType
from db.repositories.campaign_repo import CampaignRepository
from db.session import async_session_factory
from worker.session_pool import SessionPool

log = structlog.get_logger()

# Per-campaign stop signals
_stop_signals: dict[uuid.UUID, bool] = {}
# Live progress: campaign_id -> (sent, total)
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

            # Run all sessions in parallel (staggered by offset)
            tasks = []
            for tg_session, offset in sessions_map.values():
                tasks.append(self._broadcast_session(
                    campaign=campaign,
                    tg_session=tg_session,
                    chats=chats,
                    offset_seconds=offset,
                ))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for r in results:
                if isinstance(r, int):
                    sent += r

            _progress[campaign_id] = (sent, total)
            log.info("Cycle complete", campaign_id=str(campaign_id), cycle=campaign.current_cycle + 1, sent=sent)

            async with async_session_factory() as session:
                async with session.begin():
                    repo = CampaignRepository(session)
                    await repo.increment_cycle(campaign_id)

                    updated = await repo.get(campaign_id)
                    if updated and cfg.max_cycles and updated.current_cycle >= cfg.max_cycles:
                        await repo.update_status(campaign_id, CampaignStatus.COMPLETED)
                        log.info("Campaign completed max cycles", campaign_id=str(campaign_id))
                        _progress.pop(campaign_id, None)
                        return

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
    ) -> int:
        """Broadcast to all chats using one session. Returns sent count."""
        if offset_seconds > 0:
            await asyncio.sleep(offset_seconds)

        client = await self._pool.get_or_connect(tg_session)
        if not client:
            log.warning("Could not connect session", session_id=str(tg_session.id))
            return 0

        cfg = campaign.settings

        # Pre-fetch source message once if needed (copy mode)
        cached_source_msg = None
        if campaign.post.type == PostType.FORWARDED and not cfg.forward_mode:
            try:
                cached_source_msg = await client.get_messages(
                    campaign.post.source_chat_id,
                    ids=campaign.post.source_message_id,
                )
            except Exception as e:
                log.error("Cannot fetch source message", error=str(e))
                return 0

        sent = 0
        pending_logs: list[BroadcastLog] = []
        is_paused = False  # track pause state to avoid unnecessary DB hits

        i = 0
        while i < len(chats):
            chat = chats[i]
            if _stop_signals.get(campaign.id):
                break

            # Poll DB for pause only: when we know we're paused, or every 5 chats
            if is_paused or i % 5 == 0:
                async with async_session_factory() as s:
                    c = await CampaignRepository(s).get(campaign.id)
                db_status = c.status if c else None

                if db_status == CampaignStatus.PAUSED:
                    if not is_paused:
                        log.info("Campaign paused, waiting...", campaign_id=str(campaign.id))
                        is_paused = True
                    await asyncio.sleep(3)
                    continue  # re-check same chat — don't skip ahead
                else:
                    is_paused = False

            if _stop_signals.get(campaign.id):
                break

            status, message_id, error = await self._send_post(
                client=client,
                post=campaign.post,
                chat_id=chat.chat_id,
                forward_mode=cfg.forward_mode,
                cached_source_msg=cached_source_msg,
            )

            pending_logs.append(BroadcastLog(
                campaign_id=campaign.id,
                session_id=tg_session.id,
                chat_id=chat.chat_id,
                cycle=campaign.current_cycle + 1,
                message_id=message_id,
                status=status,
                error=error,
            ))

            # Flush logs every 10 chats to avoid holding too much in memory
            if len(pending_logs) >= 10:
                await self._flush_logs(pending_logs)
                pending_logs.clear()

            if status == BroadcastStatus.SUCCESS:
                sent += 1

            delay = cfg.delay_between_chats
            if cfg.randomize_delay:
                delay = random.randint(cfg.randomize_min, cfg.randomize_max)
            await asyncio.sleep(delay)
            i += 1

        # Flush remaining logs
        if pending_logs:
            await self._flush_logs(pending_logs)

        return sent

    @staticmethod
    async def _flush_logs(logs: list[BroadcastLog]) -> None:
        """Batch-write broadcast logs to DB."""
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    session.add_all(logs)
        except Exception as e:
            log.error("Failed to flush broadcast logs", error=str(e))

    async def _send_post(
        self,
        client: TelegramClient,
        post: Post,
        chat_id: int | str,
        forward_mode: bool,
        cached_source_msg=None,  # type: ignore[no-untyped-def]
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
                msg = cached_source_msg
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
                if not post.media_bytes:
                    return BroadcastStatus.SKIPPED, None, "Media bytes missing — recreate the post"
                entities = _parse_entities(post.text_entities)
                buf = io.BytesIO(post.media_bytes)
                buf.name = post.media_filename or _default_media_filename(post.type)
                result = await client.send_file(
                    entity=chat_id,
                    file=buf,
                    caption=post.text or "",
                    formatting_entities=entities,
                    force_document=(post.type == PostType.DOCUMENT),
                )
                msg_id = result.id

            else:
                # Text post
                entities = _parse_entities(post.text_entities)
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


def _default_media_filename(post_type: PostType) -> str:
    return {
        PostType.PHOTO: "photo.jpg",
        PostType.VIDEO: "video.mp4",
        PostType.DOCUMENT: "file.bin",
    }.get(post_type, "file.bin")


def _parse_entities(text_entities: str | None) -> list[tl.types.TypeMessageEntity] | None:
    if not text_entities:
        return None
    try:
        raw = json.loads(text_entities)
        if not raw:
            return None

        entities = []
        for e in raw:
            # aiogram stores 'type' as lowercase string, telethon wants MessageEntityXXX
            etype = e.get("type")
            if not etype:
                continue

            # Basic mapping from aiogram type to Telethon class name
            mapping = {
                "bold": tl.types.MessageEntityBold,
                "italic": tl.types.MessageEntityItalic,
                "underline": tl.types.MessageEntityUnderline,
                "strikethrough": tl.types.MessageEntityStrike,
                "code": tl.types.MessageEntityCode,
                "pre": tl.types.MessageEntityPre,
                "text_link": tl.types.MessageEntityTextUrl,
                "mention": tl.types.MessageEntityMention,
                "hashtag": tl.types.MessageEntityHashtag,
                "bot_command": tl.types.MessageEntityBotCommand,
                "url": tl.types.MessageEntityUrl,
                "email": tl.types.MessageEntityEmail,
                "phone_number": tl.types.MessageEntityPhone,
                "cashtag": tl.types.MessageEntityCashtag,
                "spoiler": tl.types.MessageEntitySpoiler,
                "blockquote": tl.types.MessageEntityBlockquote,
            }

            cls = mapping.get(etype)
            if not cls:
                continue

            kwargs = {"offset": e["offset"], "length": e["length"]}
            if etype == "text_link":
                kwargs["url"] = e["url"]
            if etype == "pre":
                kwargs["language"] = e.get("language", "")

            entities.append(cls(**kwargs))

        return entities if entities else None
    except Exception:
        log.error("Failed to parse entities", text_entities=text_entities)
        return None
