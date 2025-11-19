from __future__ import annotations

import asyncio
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict


@dataclass
class SessionChannel:
    events: Deque[dict[str, Any]]
    condition: asyncio.Condition | None = None
    loop: asyncio.AbstractEventLoop | None = None


class EventBroker:
    """
    Lightweight in-memory event broker keyed by sessionId.

    Tracks a small backlog of events per session and notifies active listeners
    via an asyncio.Condition. When no listeners are connected, published events
    are stored in the backlog and replayed the next time a listener subscribes.
    """

    def __init__(self, max_backlog: int = 200) -> None:
        self._lock = threading.RLock()
        self._channels: Dict[str, SessionChannel] = {}
        self._max_backlog = max_backlog

    def register(self, session_id: str) -> SessionChannel:
        loop = asyncio.get_running_loop()
        with self._lock:
            channel = self._channels.get(session_id)
            if channel is None:
                channel = SessionChannel(events=deque(maxlen=self._max_backlog))
                self._channels[session_id] = channel
            if channel.condition is None:
                channel.condition = asyncio.Condition()
            channel.loop = loop
            return channel

    def unregister(self, session_id: str) -> None:
        with self._lock:
            channel = self._channels.get(session_id)
            if channel:
                channel.loop = None

    def clear(self, session_id: str) -> int:
        """
        Remove any queued events for the given session.

        Returns the number of events discarded, which is primarily useful
        for testing and observability.
        """
        with self._lock:
            channel = self._channels.get(session_id)
            if channel is None:
                return 0
            cleared = len(channel.events)
            channel.events.clear()
            return cleared

    def publish(self, session_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            channel = self._channels.get(session_id)
            if channel is None:
                channel = SessionChannel(events=deque(maxlen=self._max_backlog))
                self._channels[session_id] = channel
            loop = channel.loop
            condition = channel.condition

        if condition is None or loop is None or not loop.is_running():
            channel.events.append(event)
            return

        asyncio.run_coroutine_threadsafe(self._push(channel, event), loop)

    async def next_event(
        self,
        session_id: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        channel = self._channels[session_id]
        condition = channel.condition

        if condition is None:
            if channel.events:
                return channel.events.popleft()
            raise asyncio.TimeoutError("No events available.")

        async with condition:
            if channel.events:
                return channel.events.popleft()

            if timeout is None:
                await condition.wait()
            else:
                await asyncio.wait_for(condition.wait(), timeout=timeout)

            if channel.events:
                return channel.events.popleft()
            raise asyncio.TimeoutError("No events available.")

    async def _push(self, channel: SessionChannel, event: dict[str, Any]) -> None:
        if channel.condition is None:
            channel.events.append(event)
            return

        async with channel.condition:
            channel.events.append(event)
            channel.condition.notify_all()


event_broker = EventBroker()


