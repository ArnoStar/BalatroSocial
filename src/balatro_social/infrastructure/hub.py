"""The event hub: the players' open event streams, in this process.

Use cases publish from the server's worker threads; each stream reads on the
event loop it was opened on (``call_soon_threadsafe`` hands events over). A
stream that falls ``queue_size`` events behind is closed: its client opens a
new one and reloads what it shows (docs/events.md)."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Iterable

from balatro_social.application.dto import Event

log = logging.getLogger(__name__)


class HubSubscription:
    def __init__(self, hub: LocalHub, player: str, loop: asyncio.AbstractEventLoop, size: int) -> None:
        self.hub = hub
        self.player = player
        self.loop = loop
        self.queue: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=size)
        self.closed = False

    def deliver(self, event: Event) -> None:
        """(On the stream's loop.)"""
        if self.closed:
            return
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("an event stream of %s fell behind: it is closed (its client opens another)", self.player)
            self.close()
            while not self.queue.empty():
                self.queue.get_nowait()
            self.queue.put_nowait(None)  # (wakes the reader up)

    async def next(self, timeout: float) -> Event | None:
        if self.closed and self.queue.empty():
            raise EOFError
        try:
            event = await asyncio.wait_for(self.queue.get(), timeout)
        except TimeoutError:
            return None
        if event is None:
            raise EOFError
        return event

    def close(self) -> None:
        self.closed = True
        self.hub.remove(self)


class LocalHub:
    def __init__(self, queue_size: int = 256) -> None:
        self.queue_size = queue_size
        self._lock = threading.Lock()
        self._streams: dict[str, set[HubSubscription]] = {}

    def subscribe(self, player: str) -> HubSubscription:
        sub = HubSubscription(self, player, asyncio.get_running_loop(), self.queue_size)
        with self._lock:
            self._streams.setdefault(player, set()).add(sub)
        return sub

    def remove(self, sub: HubSubscription) -> None:
        with self._lock:
            subs = self._streams.get(sub.player)
            if subs is not None:
                subs.discard(sub)
                if not subs:
                    del self._streams[sub.player]

    def publish(self, players: Iterable[str], event: Event) -> None:
        with self._lock:
            subs = [s for p in set(players) for s in self._streams.get(p, ())]
        for s in subs:
            try:
                s.loop.call_soon_threadsafe(s.deliver, event)
            except RuntimeError:  # (its loop has stopped: the server is shutting down)
                pass

    def streams(self, player: str) -> int:
        with self._lock:
            return len(self._streams.get(player, ()))
