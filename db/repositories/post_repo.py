from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Post, PostType


class PostRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, post_id: uuid.UUID) -> Post | None:
        return await self._session.get(Post, post_id)

    async def get_by_user(self, user_id: int) -> list[Post]:
        result = await self._session.execute(
            select(Post)
            .where(Post.user_id == user_id)
            .order_by(Post.created_at.desc())
        )
        return list(result.scalars().all())

    async def create_forwarded(
        self,
        user_id: int,
        title: str,
        source_chat_id: int,
        source_message_id: int,
    ) -> Post:
        post = Post(
            user_id=user_id,
            title=title,
            type=PostType.FORWARDED,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
        )
        self._session.add(post)
        await self._session.flush()
        return post

    async def create_manual(
        self,
        user_id: int,
        title: str,
        post_type: PostType,
        text: str | None = None,
        text_entities: str | None = None,
        media_file_id: str | None = None,
        media_type: str | None = None,
    ) -> Post:
        post = Post(
            user_id=user_id,
            title=title,
            type=post_type,
            text=text,
            text_entities=text_entities,
            media_file_id=media_file_id,
            media_type=media_type,
        )
        self._session.add(post)
        await self._session.flush()
        return post

    async def delete(self, post_id: uuid.UUID) -> None:
        post = await self.get(post_id)
        if post:
            await self._session.delete(post)
            await self._session.flush()
