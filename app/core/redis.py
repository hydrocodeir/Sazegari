from __future__ import annotations

import logging
from typing import Optional

import redis
from redis import Redis

from app.core.config import settings

logger = logging.getLogger("water_compat.redis")

_client: Optional[Redis] = None


def get_redis() -> Optional[Redis]:
    """Return a singleton Redis client (or None if not reachable)."""
    global _client
    if _client is not None:
        return _client
    try:
        _client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        _client.ping()
        return _client
    except Exception as exc:
        logger.warning("Redis unavailable: %s", exc)
        _client = None
        return None
