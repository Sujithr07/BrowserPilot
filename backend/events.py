"""
Cross-process event bus over Redis pub/sub.

In queue mode the crew runs in the WORKER process while the WebSocket lives in
the API process, so progress can't be handed over an in-memory dict. Instead:

  worker  --publish-->  af:events:{task_id}   --subscribe-->  API --> WebSocket
  WebSocket --LPUSH/ publish--> af:approval:{task_id} --subscribe--> worker

Forward direction carries progress events (including the `approval_required`
prompt). Reverse direction carries the human's approval decision back to the
worker, which is blocked awaiting it. Both use short-lived pub/sub subscriptions;
ordering is safe because the worker subscribes to the approval channel *before*
it publishes the approval_required prompt.
"""
import json
import asyncio
from contextlib import asynccontextmanager

import redis.asyncio as aioredis

from backend.logging_config import get_logger

log = get_logger("agentflow.events")


def _events_channel(task_id: str) -> str:
    return f"af:events:{task_id}"


def _approval_channel(task_id: str) -> str:
    return f"af:approval:{task_id}"


def _stop_channel(task_id: str) -> str:
    return f"af:stop:{task_id}"


class EventBus:
    def __init__(self, redis_url: str):
        # decode_responses so pub/sub payloads come back as str, not bytes.
        self._redis = aioredis.from_url(redis_url, decode_responses=True)

    async def close(self) -> None:
        await self._redis.aclose()

    # ── Forward: worker -> API/WebSocket ────────────────────────────────────
    async def publish_event(self, task_id: str, event: str, data: dict) -> None:
        await self._redis.publish(
            _events_channel(task_id), json.dumps({"event": event, "data": data})
        )

    @asynccontextmanager
    async def subscribe_events(self, task_id: str):
        """Yield an async iterator of {event, data} dicts for a task.

        Used by the WS handler; cancel the consuming task to stop. The pubsub is
        always cleaned up on exit.
        """
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(_events_channel(task_id))

        async def _iter():
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    yield json.loads(message["data"])

        try:
            yield _iter()
        finally:
            try:
                await pubsub.unsubscribe(_events_channel(task_id))
                await pubsub.aclose()
            except Exception:
                pass

    # ── Reverse: API/WebSocket -> worker (stop requests) ─────────────────────
    async def send_stop(self, task_id: str) -> None:
        """Ask the worker running `task_id` to cancel. Fire-and-forget pub/sub:
        if the worker isn't subscribed (already finished) the message is dropped."""
        await self._redis.publish(_stop_channel(task_id), json.dumps({"stop": True}))

    @asynccontextmanager
    async def subscribe_stop(self, task_id: str):
        """Yield an async iterator that emits once when a stop is requested.

        The worker consumes the first item to set its cancel Event, then the
        subscription is torn down on exit.
        """
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(_stop_channel(task_id))

        async def _iter():
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    yield json.loads(message["data"])

        try:
            yield _iter()
        finally:
            try:
                await pubsub.unsubscribe(_stop_channel(task_id))
                await pubsub.aclose()
            except Exception:
                pass

    # ── Reverse: API/WebSocket -> worker (approval decisions) ────────────────
    async def send_approval(self, task_id: str, approved: bool) -> None:
        await self._redis.publish(
            _approval_channel(task_id), json.dumps({"approved": approved})
        )

    async def wait_approval(
        self, task_id: str, timeout: float, after_subscribe=None
    ) -> dict | None:
        """
        Block until an approval decision arrives, or return None on timeout.

        `after_subscribe` (an async callable) runs immediately AFTER we subscribe
        but BEFORE we wait — the worker uses it to publish the `approval_required`
        prompt, guaranteeing the subscription is live before any reply can arrive
        (so a fast/auto approver can't beat us to it).
        """
        channel = _approval_channel(task_id)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        if after_subscribe is not None:
            await after_subscribe()
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return None
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=remaining
                )
                if message and message.get("type") == "message":
                    return json.loads(message["data"])
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception:
                pass
