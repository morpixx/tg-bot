from __future__ import annotations

import uuid

import pytest

from db.models import CampaignStatus
from db.repositories.campaign_repo import CampaignRepository


pytestmark = pytest.mark.integration


async def test_create_campaign(db_session, db_user, db_post) -> None:
    repo = CampaignRepository(db_session)
    campaign = await repo.create(db_user.tg_id, "My Campaign", db_post.id)
    assert campaign.id is not None
    assert campaign.name == "My Campaign"
    assert campaign.status == CampaignStatus.DRAFT
    assert campaign.current_cycle == 0


async def test_create_campaign_has_default_settings(db_session, db_campaign) -> None:
    repo = CampaignRepository(db_session)
    campaign = await repo.get(db_campaign.id, load_relations=True)
    assert campaign.settings is not None
    assert campaign.settings.delay_between_chats == 5
    assert campaign.settings.forward_mode is True
    assert campaign.settings.randomize_delay is False


async def test_get_campaign(db_session, db_campaign) -> None:
    repo = CampaignRepository(db_session)
    found = await repo.get(db_campaign.id)
    assert found is not None
    assert found.id == db_campaign.id


async def test_get_missing_returns_none(db_session) -> None:
    repo = CampaignRepository(db_session)
    assert await repo.get(uuid.uuid4()) is None


async def test_get_by_user(db_session, db_user, db_campaign) -> None:
    repo = CampaignRepository(db_session)
    campaigns = await repo.get_by_user(db_user.tg_id)
    ids = [c.id for c in campaigns]
    assert db_campaign.id in ids


async def test_update_status(db_session, db_campaign) -> None:
    repo = CampaignRepository(db_session)
    await repo.update_status(db_campaign.id, CampaignStatus.ACTIVE)
    found = await repo.get(db_campaign.id)
    assert found.status == CampaignStatus.ACTIVE


async def test_update_settings(db_session, db_campaign) -> None:
    repo = CampaignRepository(db_session)
    await repo.update_settings(
        db_campaign.id,
        delay_between_chats=15,
        randomize_delay=True,
        shuffle_after_cycle=True,
        max_cycles=5,
        forward_mode=False,
    )
    campaign = await repo.get(db_campaign.id, load_relations=True)
    cfg = campaign.settings
    assert cfg.delay_between_chats == 15
    assert cfg.randomize_delay is True
    assert cfg.shuffle_after_cycle is True
    assert cfg.max_cycles == 5
    assert cfg.forward_mode is False


async def test_increment_cycle(db_session, db_campaign) -> None:
    repo = CampaignRepository(db_session)
    await repo.increment_cycle(db_campaign.id)
    await repo.increment_cycle(db_campaign.id)
    found = await repo.get(db_campaign.id)
    assert found.current_cycle == 2


async def test_set_sessions(db_session, db_campaign, db_tg_session) -> None:
    repo = CampaignRepository(db_session)
    await repo.set_sessions(db_campaign.id, {db_tg_session.id: 120})
    campaign = await repo.get(db_campaign.id, load_relations=True)
    assert len(campaign.campaign_sessions) == 1
    cs = campaign.campaign_sessions[0]
    assert cs.session_id == db_tg_session.id
    assert cs.delay_offset_seconds == 120


async def test_set_sessions_replaces_old(db_session, db_campaign, db_tg_session) -> None:
    repo = CampaignRepository(db_session)
    # First set
    await repo.set_sessions(db_campaign.id, {db_tg_session.id: 0})
    # Replace with different offset
    await repo.set_sessions(db_campaign.id, {db_tg_session.id: 300})
    campaign = await repo.get(db_campaign.id, load_relations=True)
    assert len(campaign.campaign_sessions) == 1
    assert campaign.campaign_sessions[0].delay_offset_seconds == 300


async def test_set_chats(db_session, db_campaign, db_chat) -> None:
    repo = CampaignRepository(db_session)
    await repo.set_chats(db_campaign.id, [db_chat.id])
    campaign = await repo.get(db_campaign.id, load_relations=True)
    assert len(campaign.campaign_chats) == 1
    assert campaign.campaign_chats[0].chat_id == db_chat.id


async def test_set_chats_maintains_order(db_session, db_campaign, db_user) -> None:
    from db.models import TargetChat
    c1 = TargetChat(user_id=db_user.tg_id, chat_id=-7001, title="C1", position=0)
    c2 = TargetChat(user_id=db_user.tg_id, chat_id=-7002, title="C2", position=1)
    c3 = TargetChat(user_id=db_user.tg_id, chat_id=-7003, title="C3", position=2)
    db_session.add_all([c1, c2, c3])
    await db_session.flush()

    repo = CampaignRepository(db_session)
    await repo.set_chats(db_campaign.id, [c3.id, c1.id, c2.id])
    campaign = await repo.get(db_campaign.id, load_relations=True)
    chat_ids = [cc.chat_id for cc in campaign.campaign_chats]
    assert chat_ids == [-7003, -7001, -7002]


async def test_get_active_campaigns(db_session, db_user, db_campaign) -> None:
    repo = CampaignRepository(db_session)
    await repo.update_status(db_campaign.id, CampaignStatus.ACTIVE)
    active = await repo.get_active()
    ids = [c.id for c in active]
    assert db_campaign.id in ids


async def test_get_active_excludes_paused(db_session, db_campaign) -> None:
    repo = CampaignRepository(db_session)
    await repo.update_status(db_campaign.id, CampaignStatus.PAUSED)
    active = await repo.get_active()
    ids = [c.id for c in active]
    assert db_campaign.id not in ids


async def test_delete_campaign(db_session, db_campaign) -> None:
    repo = CampaignRepository(db_session)
    await repo.delete(db_campaign.id)
    assert await repo.get(db_campaign.id) is None


async def test_load_relations_eager(db_session, db_campaign, db_tg_session, db_chat) -> None:
    repo = CampaignRepository(db_session)
    await repo.set_sessions(db_campaign.id, {db_tg_session.id: 0})
    await repo.set_chats(db_campaign.id, [db_chat.id])

    campaign = await repo.get(db_campaign.id, load_relations=True)
    assert campaign.settings is not None
    assert len(campaign.campaign_sessions) == 1
    assert len(campaign.campaign_chats) == 1
    # Related objects should be loaded
    assert campaign.campaign_sessions[0].session is not None
    assert campaign.campaign_chats[0].chat is not None
