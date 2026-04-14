from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import UserSettings


class UserSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(self, user_id: int) -> UserSettings:
        obj = await self._session.get(UserSettings, user_id)
        if obj is None:
            obj = UserSettings(user_id=user_id)
            self._session.add(obj)
            await self._session.flush()
        return obj

    async def update(self, user_id: int, **kwargs: object) -> UserSettings:
        obj = await self.get_or_create(user_id)
        for key, val in kwargs.items():
            setattr(obj, key, val)
        await self._session.flush()
        return obj
