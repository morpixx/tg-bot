from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bot.filters.admin import IsOwner


def _make_event(user_id: int | None) -> MagicMock:
    event = MagicMock()
    if user_id is None:
        event.from_user = None
    else:
        event.from_user = MagicMock()
        event.from_user.id = user_id
    return event


@pytest.fixture(autouse=True)
def patch_settings():
    with patch("bot.filters.admin.settings") as s:
        s.owner_id = 999999
        yield s


async def test_owner_passes() -> None:
    assert await IsOwner()(_make_event(999999)) is True


async def test_non_owner_blocked() -> None:
    assert await IsOwner()(_make_event(111111)) is False


async def test_zero_id_blocked() -> None:
    assert await IsOwner()(_make_event(0)) is False


async def test_no_user_blocked() -> None:
    assert await IsOwner()(_make_event(None)) is False


async def test_negative_id_blocked() -> None:
    assert await IsOwner()(_make_event(-1)) is False


async def test_owner_id_exact_match(patch_settings) -> None:
    patch_settings.owner_id = 42
    assert await IsOwner()(_make_event(42)) is True
    assert await IsOwner()(_make_event(43)) is False
