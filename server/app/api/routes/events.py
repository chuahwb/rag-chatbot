from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Query
from starlette.responses import StreamingResponse

from app.agents.events import event_broker
from app.core.config import get_settings

router = APIRouter(prefix="/events", tags=["events"])


async def _event_stream(session_id: str, *, max_events: int | None = None) -> AsyncIterator[bytes]:
    event_broker.register(session_id)
    emitted = 0
    try:
        ready_payload = json.dumps({"sessionId": session_id, "status": "ready"})
        yield f"event: ready\ndata: {ready_payload}\n\n".encode("utf-8")
        emitted += 1
        if max_events is not None and emitted >= max_events:
            return

        while True:
            try:
                event = await event_broker.next_event(session_id, timeout=10.0)
            except asyncio.TimeoutError:
                heartbeat = json.dumps({"sessionId": session_id, "status": "idle"})
                yield f"event: heartbeat\ndata: {heartbeat}\n\n".encode("utf-8")
                continue

            payload = json.dumps(event)
            event_type = event.get("type", "message")
            data = f"event: {event_type}\ndata: {payload}\n\n"
            yield data.encode("utf-8")
            emitted += 1
            if max_events is not None and emitted >= max_events:
                return
    finally:
        event_broker.unregister(session_id)


@router.get("")
async def stream_session_events(
    session_id: str = Query(..., alias="sessionId", min_length=1),
    max_events: int | None = Query(default=None, alias="maxEvents", ge=1, le=100),
) -> StreamingResponse:
    settings = get_settings()
    if not settings.enable_sse:
        raise HTTPException(status_code=404, detail="SSE streaming is disabled.")

    generator = _event_stream(session_id, max_events=max_events)
    return StreamingResponse(generator, media_type="text/event-stream")


