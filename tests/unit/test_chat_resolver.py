from __future__ import annotations

import pytest

from services.chat_resolver import (
    ResolverError,
    from_forwarded_chat,
    parse_input,
)


class TestParseInput:
    def test_at_username(self) -> None:
        assert parse_input("@channel") == "channel"

    def test_bare_username(self) -> None:
        assert parse_input("channel") == "channel"

    def test_tme_link(self) -> None:
        assert parse_input("https://t.me/channel") == "channel"

    def test_tme_link_no_https(self) -> None:
        assert parse_input("t.me/channel") == "channel"

    def test_tme_link_trailing_slash(self) -> None:
        assert parse_input("https://t.me/channel/") == "channel"

    def test_negative_id(self) -> None:
        assert parse_input("-1001234567890") == -1001234567890

    def test_positive_id(self) -> None:
        assert parse_input("123456") == 123456

    def test_invite_link_rejected(self) -> None:
        with pytest.raises(ResolverError, match="Приватные invite"):
            parse_input("https://t.me/+abcDEF123_-")

    def test_invite_link_short_rejected(self) -> None:
        with pytest.raises(ResolverError, match="Приватные invite"):
            parse_input("t.me/+abc")

    def test_empty_rejected(self) -> None:
        with pytest.raises(ResolverError, match="Пустой"):
            parse_input("   ")

    def test_garbage_rejected(self) -> None:
        with pytest.raises(ResolverError, match="Не понял"):
            parse_input("!!!")


class TestFromForwardedChat:
    def test_normal_forward(self) -> None:
        chat = type("Chat", (), {"id": -100123, "title": "Test", "username": "test"})()
        r = from_forwarded_chat(chat)
        assert r.chat_id == -100123
        assert r.title == "Test"
        assert r.username == "test"

    def test_forward_no_username(self) -> None:
        chat = type("Chat", (), {"id": -100456, "title": "Private", "username": None})()
        r = from_forwarded_chat(chat)
        assert r.username is None

    def test_forward_no_title(self) -> None:
        chat = type("Chat", (), {"id": -100789, "title": None, "username": None})()
        r = from_forwarded_chat(chat)
        assert r.title == "-100789"

    def test_none_rejected(self) -> None:
        with pytest.raises(ResolverError, match="скрыл"):
            from_forwarded_chat(None)
