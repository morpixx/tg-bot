from __future__ import annotations

from cachetools import TTLCache  # type: ignore[import-untyped]

# Cached detached User ORM instances (keyed by tg_id). Short TTL — user
# metadata rarely changes but still needs refresh so username/full_name
# updates propagate without a restart.
user_cache: TTLCache = TTLCache(maxsize=10_000, ttl=60)

# Cached subscription status per user: tg_id -> (all_subscribed, missing_ids).
# Short TTL so a user who just joined a channel can pass the gate quickly.
subscription_cache: TTLCache = TTLCache(maxsize=10_000, ttl=30)

# Channel metadata: channel_id -> (title, invite_url). Long TTL — titles and
# invite URLs are stable.
channel_info_cache: TTLCache = TTLCache(maxsize=1_000, ttl=600)


def invalidate_user(tg_id: int) -> None:
    user_cache.pop(tg_id, None)
    subscription_cache.pop(tg_id, None)
