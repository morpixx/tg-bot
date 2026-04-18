from __future__ import annotations

from unittest.mock import MagicMock, patch

from aiogram.exceptions import TelegramForbiddenError

from services.subscription import check_subscriptions, get_channel_invite_links

# ── check_subscriptions ───────────────────────────────────────────────────────

async def test_no_channels_configured_passes(mock_bot) -> None:
    with patch("services.subscription.settings") as s:
        s.required_channel_ids = []
        ok, missing = await check_subscriptions(mock_bot, 111)
    assert ok is True
    assert missing == []


async def test_member_passes(mock_bot) -> None:
    member = MagicMock()
    member.status = "member"
    mock_bot.get_chat_member.return_value = member

    with patch("services.subscription.settings") as s:
        s.required_channel_ids = [-1001]
        ok, missing = await check_subscriptions(mock_bot, 111)

    assert ok is True
    assert missing == []


async def test_left_member_blocked(mock_bot) -> None:
    member = MagicMock()
    member.status = "left"
    mock_bot.get_chat_member.return_value = member

    with patch("services.subscription.settings") as s:
        s.required_channel_ids = [-1001]
        ok, missing = await check_subscriptions(mock_bot, 111)

    assert ok is False
    assert -1001 in missing


async def test_kicked_member_blocked(mock_bot) -> None:
    member = MagicMock()
    member.status = "kicked"
    mock_bot.get_chat_member.return_value = member

    with patch("services.subscription.settings") as s:
        s.required_channel_ids = [-1001]
        ok, missing = await check_subscriptions(mock_bot, 111)

    assert ok is False


async def test_forbidden_error_skips_channel(mock_bot) -> None:
    mock_bot.get_chat_member.side_effect = TelegramForbiddenError(method=MagicMock(), message="Forbidden")

    with patch("services.subscription.settings") as s:
        s.required_channel_ids = [-1001]
        ok, missing = await check_subscriptions(mock_bot, 111)

    # Skip inaccessible channels — don't block user
    assert ok is True


async def test_multiple_channels_all_subscribed(mock_bot) -> None:
    member = MagicMock()
    member.status = "member"
    mock_bot.get_chat_member.return_value = member

    with patch("services.subscription.settings") as s:
        s.required_channel_ids = [-1001, -1002, -1003]
        ok, missing = await check_subscriptions(mock_bot, 111)

    assert ok is True
    assert missing == []


async def test_multiple_channels_partial_subscribed(mock_bot) -> None:
    def side_effect(chat_id, user_id):
        m = MagicMock()
        m.status = "left" if chat_id == -1002 else "member"
        return m

    mock_bot.get_chat_member.side_effect = side_effect

    with patch("services.subscription.settings") as s:
        s.required_channel_ids = [-1001, -1002, -1003]
        ok, missing = await check_subscriptions(mock_bot, 111)

    assert ok is False
    assert missing == [-1002]


# ── get_channel_invite_links ──────────────────────────────────────────────────

async def test_invite_link_public_channel(mock_bot) -> None:
    chat = MagicMock()
    chat.username = "mychannel"
    mock_bot.get_chat.return_value = chat

    links = await get_channel_invite_links(mock_bot, [-1001])
    assert links[-1001] == "https://t.me/mychannel"


async def test_invite_link_private_channel(mock_bot) -> None:
    chat = MagicMock()
    chat.username = None
    mock_bot.get_chat.return_value = chat

    link_obj = MagicMock()
    link_obj.invite_link = "https://t.me/+ABC123"
    mock_bot.create_chat_invite_link.return_value = link_obj

    links = await get_channel_invite_links(mock_bot, [-1001])
    assert links[-1001] == "https://t.me/+ABC123"


async def test_invite_link_error_fallback(mock_bot) -> None:
    mock_bot.get_chat.side_effect = Exception("error")

    links = await get_channel_invite_links(mock_bot, [-1001])
    assert links[-1001] == "-1001"
