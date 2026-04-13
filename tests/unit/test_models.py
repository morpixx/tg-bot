from __future__ import annotations

import pytest

from db.models import BroadcastStatus, CampaignStatus, PostType


class TestPostType:
    def test_all_values(self) -> None:
        assert PostType.FORWARDED == "forwarded"
        assert PostType.TEXT == "text"
        assert PostType.PHOTO == "photo"
        assert PostType.VIDEO == "video"
        assert PostType.DOCUMENT == "document"
        assert PostType.MEDIA_GROUP == "media_group"

    def test_from_string(self) -> None:
        assert PostType("text") is PostType.TEXT
        assert PostType("video") is PostType.VIDEO

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            PostType("unknown")

    def test_is_str(self) -> None:
        assert isinstance(PostType.TEXT, str)


class TestCampaignStatus:
    def test_all_values(self) -> None:
        assert CampaignStatus.DRAFT == "draft"
        assert CampaignStatus.ACTIVE == "active"
        assert CampaignStatus.PAUSED == "paused"
        assert CampaignStatus.STOPPED == "stopped"
        assert CampaignStatus.COMPLETED == "completed"

    def test_from_string(self) -> None:
        assert CampaignStatus("active") is CampaignStatus.ACTIVE

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            CampaignStatus("running")


class TestBroadcastStatus:
    def test_all_values(self) -> None:
        assert BroadcastStatus.SUCCESS == "success"
        assert BroadcastStatus.FAILED == "failed"
        assert BroadcastStatus.FLOOD_WAIT == "flood_wait"
        assert BroadcastStatus.SKIPPED == "skipped"

    def test_from_string(self) -> None:
        assert BroadcastStatus("flood_wait") is BroadcastStatus.FLOOD_WAIT
