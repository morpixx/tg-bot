from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import TargetChat


class ChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, chat_id: uuid.UUID) -> TargetChat | None:
        return await self._session.get(TargetChat, chat_id)

    async def get_by_user(self, user_id: int) -> list[TargetChat]:
        result = await self._session.execute(
            select(TargetChat)
            .where(TargetChat.user_id == user_id)
            .order_by(TargetChat.position)
        )
        return list(result.scalars().all())

    async def find_by_chat_id(self, user_id: int, chat_id: int) -> TargetChat | None:
        result = await self._session.execute(
            select(TargetChat).where(
                TargetChat.user_id == user_id,
                TargetChat.chat_id == chat_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        user_id: int,
        chat_id: int,
        title: str,
        username: str | None = None,
    ) -> TargetChat:
        # Position = last + 1
        existing = await self.get_by_user(user_id)
        position = len(existing)
        chat = TargetChat(
            user_id=user_id,
            chat_id=chat_id,
            title=title,
            username=username,
            position=position,
        )
        self._session.add(chat)
        await self._session.flush()
        return chat

    async def delete(self, chat_id: uuid.UUID) -> None:
        chat = await self.get(chat_id)
        if chat:
            await self._session.delete(chat)
            await self._session.flush()

    async def bulk_create(self, user_id: int, chats: list[dict]) -> list[TargetChat]:
        """Import multiple chats at once. Skips duplicates."""
        existing_ids = {c.chat_id for c in await self.get_by_user(user_id)}
        position = len(existing_ids)
        created = []
        for item in chats:
            if item["chat_id"] in existing_ids:
                continue
            chat = TargetChat(
                user_id=user_id,
                chat_id=item["chat_id"],
                title=item["title"],
                username=item.get("username"),
                position=position,
            )
            self._session.add(chat)
            existing_ids.add(item["chat_id"])
            position += 1
            created.append(chat)
        if created:
            await self._session.flush()
        return created
