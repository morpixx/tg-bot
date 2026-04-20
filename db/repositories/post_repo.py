from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Campaign, Post, PostMediaItem, PostType


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
        media_type: str | None = None,
        media_bytes: bytes | None = None,
        media_filename: str | None = None,
    ) -> Post:
        post = Post(
            user_id=user_id,
            title=title,
            type=post_type,
            text=text,
            text_entities=text_entities,
            media_type=media_type,
            media_bytes=media_bytes,
            media_filename=media_filename,
        )
        self._session.add(post)
        await self._session.flush()
        return post

    async def create_media_group(
        self,
        user_id: int,
        title: str,
        text: str | None,
        text_entities: str | None,
        items: list[dict],
    ) -> Post:
        """Create an album post with multiple media items.

        items: list of {"type": "photo"|"video"|"document", "bytes": bytes, "filename": str|None}
        """
        post = Post(
            user_id=user_id,
            title=title,
            type=PostType.MEDIA_GROUP,
            text=text,
            text_entities=text_entities,
        )
        self._session.add(post)
        await self._session.flush()
        for pos, item in enumerate(items):
            self._session.add(PostMediaItem(
                post_id=post.id,
                position=pos,
                media_type=item["type"],
                media_bytes=item["bytes"],
                media_filename=item.get("filename"),
            ))
        await self._session.flush()
        return post

    async def count_media_items(self, post_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(PostMediaItem).where(PostMediaItem.post_id == post_id)
        )
        return int(result.scalar() or 0)

    async def count_campaigns(self, post_id: uuid.UUID) -> int:
        """How many campaigns reference this post (blocks deletion if > 0)."""
        result = await self._session.execute(
            select(func.count()).select_from(Campaign).where(Campaign.post_id == post_id)
        )
        return int(result.scalar() or 0)

    async def delete(self, post_id: uuid.UUID) -> None:
        post = await self.get(post_id)
        if post:
            await self._session.delete(post)
            await self._session.flush()
