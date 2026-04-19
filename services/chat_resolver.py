from __future__ import annotations

import re
from dataclasses import dataclass

import structlog
from opentele2.tl import TelegramClient
from telethon.utils import get_peer_id

log = structlog.get_logger()


@dataclass
class ResolvedChat:
    chat_id: int
    title: str
    username: str | None


class ResolverError(Exception):
    """User-facing resolution failure with a friendly Russian message."""


_TME_USERNAME = re.compile(r"^(?:https?://)?t\.me/(?!\+)([A-Za-z0-9_]+)/?$")
_TME_INVITE = re.compile(r"^(?:https?://)?t\.me/\+[A-Za-z0-9_-]+/?$")


def parse_input(raw: str) -> int | str:
    """Normalize user input to either a numeric chat ID or a bare username.

    Raises ResolverError for invite links (t.me/+hash) — we don't auto-join.
    """
    text = raw.strip()
    if not text:
        raise ResolverError("Пустой ввод.")

    if _TME_INVITE.match(text):
        raise ResolverError(
            "Приватные invite-ссылки (t.me/+...) не поддерживаются. "
            "Перешли любое сообщение из чата или используй кнопку «📲 Выбрать из своих чатов»."
        )

    m = _TME_USERNAME.match(text)
    if m:
        return m.group(1)

    if text.startswith("@"):
        return text[1:]

    try:
        return int(text)
    except ValueError:
        if re.fullmatch(r"[A-Za-z0-9_]{4,}", text):
            return text
        raise ResolverError(
            "Не понял формат. Поддерживается: @username, t.me/username, "
            "числовой ID (-100…) или пересланное сообщение."
        ) from None


async def resolve(client: TelegramClient, raw: str) -> ResolvedChat:
    """Resolve user input to a ResolvedChat via an authorized client.

    Raises ResolverError on any failure with a user-friendly message.
    """
    target = parse_input(raw)
    try:
        entity = await client.get_entity(target)
    except ValueError as e:
        raise ResolverError(f"Чат не найден: {e}") from e
    except Exception as e:
        log.warning("get_entity failed", target=target, error=str(e))
        raise ResolverError(
            "Сессия не видит этот чат. Убедись, что аккаунт сессии состоит в нём."
        ) from e

    return _from_entity(entity)


def _from_entity(entity: object) -> ResolvedChat:
    chat_id = get_peer_id(entity)
    title = (
        getattr(entity, "title", None)
        or " ".join(
            filter(None, [getattr(entity, "first_name", None), getattr(entity, "last_name", None)])
        ).strip()
        or str(chat_id)
    )
    username = getattr(entity, "username", None)
    return ResolvedChat(chat_id=chat_id, title=title, username=username)


def from_forwarded_chat(forward_from_chat) -> ResolvedChat:  # type: ignore[no-untyped-def]
    """Build a ResolvedChat from aiogram's Message.forward_from_chat (a Chat object)."""
    if forward_from_chat is None:
        raise ResolverError(
            "Это сообщение без указания источника — пользователь скрыл его настройками "
            "приватности. Перешли что-нибудь из канала/группы напрямую."
        )
    return ResolvedChat(
        chat_id=forward_from_chat.id,
        title=forward_from_chat.title or str(forward_from_chat.id),
        username=getattr(forward_from_chat, "username", None),
    )
