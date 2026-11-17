"""``GET /v1/events``: the caller's live events, as server-sent events (docs/events.md).

The stream starts with ``hello`` (the caller's MeView), then sends each event
as it happens and a comment every ``heartbeat`` seconds (proxies close idle
connections). It ends when the access token expires (``expired``: reconnect
with a fresh one) or when it falls behind (``reset``: reconnect and reload).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from balatro_social.presentation.http.deps import CurrentPlayer, Uses

router = APIRouter(prefix="/v1", tags=["events"])

HEADERS = {
    "Cache-Control": "no-cache",
    # nginx (the portal's, and a proxy in front of it) passes each event on at once
    "X-Accel-Buffering": "no",
}


def frame(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(jsonable_encoder(data), separators=(',', ':'))}\n\n"


@router.get("/events", summary="Your live events (server-sent events)",
            responses={200: {"content": {"text/event-stream": {}},
                             "description": "hello, then message, message_deleted, read, typing, conversation, "
                                            "conversation_left, friend_request, friend, friend_removed, presence, "
                                            "invite, me; ends with expired or reset"}})
async def events(request: Request, player: CurrentPlayer, uses: Uses) -> StreamingResponse:
    """Open it with ``fetch`` and the ``Authorization`` header (an EventSource can't send one). While a stream
    is open the player is online for their friends."""
    sub = uses.subscribe(player)
    closed = False

    def close() -> None:
        nonlocal closed
        if not closed:
            closed = True
            sub.close()
            uses.stream_closed(player)

    try:
        hello = await run_in_threadpool(uses.stream_opened, player)
    except BaseException:
        close()
        raise
    heartbeat: float = request.app.state.heartbeat

    async def frames() -> AsyncIterator[str]:
        try:
            yield frame("hello", hello)
            while True:
                wait = heartbeat
                if player.expires_at is not None:
                    left = (player.expires_at - datetime.now(UTC)).total_seconds()
                    if left <= 0:
                        yield frame("expired", {})
                        return
                    wait = min(wait, left)
                try:
                    event = await sub.next(wait)
                except EOFError:
                    yield frame("reset", {})
                    return
                yield frame(event.type, event.data) if event is not None else ": ping\n\n"
        finally:
            close()

    # (the generator's own cleanup may not run when the client goes away first: the task runs then)
    return StreamingResponse(frames(), media_type="text/event-stream", headers=HEADERS,
                             background=BackgroundTask(close))
