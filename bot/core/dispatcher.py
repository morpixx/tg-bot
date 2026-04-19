from __future__ import annotations

from aiogram import Dispatcher
from aiogram.fsm.storage.redis import RedisStorage

from bot.core.config import settings
from bot.handlers import (
    admin,
    campaigns,
    chats,
    posts,
    sessions,
    start,
    stats,
)
from bot.handlers import (
    settings as settings_handlers,
)
from bot.middlewares.subscription import SubscriptionMiddleware
from bot.middlewares.user import UserMiddleware


def create_dispatcher() -> Dispatcher:
    storage = RedisStorage.from_url(settings.redis_url)
    dp = Dispatcher(storage=storage)

    # Middlewares (order matters)
    dp.message.middleware(UserMiddleware())
    dp.callback_query.middleware(UserMiddleware())
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())

    # Admin router first — IsOwner filter bypasses subscription gate
    dp.include_router(admin.router)

    # Operator routers.
    # campaigns.router MUST come before posts.router: the campaign-create wizard
    # has a state-filtered `post:view:` handler (for picking a post inside the
    # flow). If posts.router were checked first, its unfiltered `post:view:`
    # handler would swallow the click and break the flow.
    dp.include_router(start.router)
    dp.include_router(sessions.router)
    dp.include_router(campaigns.router)
    dp.include_router(posts.router)
    dp.include_router(chats.router)
    dp.include_router(settings_handlers.router)
    dp.include_router(stats.router)

    return dp
