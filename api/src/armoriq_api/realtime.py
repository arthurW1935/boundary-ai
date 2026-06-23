from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from redis import asyncio as redis_asyncio


class EventBroker:
    def __init__(self, redis_url: str | None) -> None:
        self.redis_url = redis_url
        self.redis = None
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    async def connect(self) -> None:
        if self.redis_url:
            self.redis = redis_asyncio.from_url(self.redis_url, decode_responses=True)

    async def close(self) -> None:
        if self.redis is not None:
            await self.redis.aclose()

    async def publish(self, event: dict[str, Any]) -> None:
        for subscriber in list(self.subscribers):
            await subscriber.put(event)

        if self.redis is not None:
            await self.redis.publish("armoriq.events", json.dumps(event, default=str))

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.subscribers.add(queue)
        try:
            yield queue
        finally:
            self.subscribers.discard(queue)
