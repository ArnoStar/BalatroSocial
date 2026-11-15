"""Who is online, in this process: a player with an open event stream (the
portal), or whose game sent its heartbeat less than PRESENCE_TTL ago, and what
that game said they were doing. A closed stream keeps its player online for a
few seconds (``grace``): reopening it (a new access token, another page)
doesn't make them flicker offline for their friends."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

from balatro_social.application.ports import PresenceState
from balatro_social.domain import PRESENCE_TTL, Activity


class PresenceBoard:
    def __init__(self, ttl: timedelta = PRESENCE_TTL, grace: timedelta = timedelta(seconds=10)) -> None:
        self.ttl = ttl
        self.grace = grace
        self._lock = threading.Lock()
        self._streams: dict[str, int] = {}
        self._closed_at: dict[str, datetime] = {}  # when the player's last stream closed
        self._beats: dict[str, tuple[datetime, Activity | None]] = {}  # the game's last heartbeat
        self._online: set[str] = set()  # the players their friends were told are online

    def _beat(self, player: str, now: datetime) -> tuple[datetime, Activity | None] | None:
        beat = self._beats.get(player)
        return beat if beat is not None and now - beat[0] < self.ttl else None

    def _is_online(self, player: str, now: datetime) -> bool:
        if self._streams.get(player, 0) > 0 or self._beat(player, now) is not None:
            return True
        closed = self._closed_at.get(player)
        return closed is not None and now - closed < self.grace

    def connect(self, player: str, now: datetime) -> bool:
        with self._lock:
            self._streams[player] = self._streams.get(player, 0) + 1
            self._closed_at.pop(player, None)
            if player in self._online:
                return False
            self._online.add(player)
            return True

    def disconnect(self, player: str, now: datetime) -> None:
        with self._lock:
            n = self._streams.get(player, 0) - 1
            if n > 0:
                self._streams[player] = n
            else:
                self._streams.pop(player, None)
                self._closed_at[player] = now

    def beat(self, player: str, activity: Activity | None, now: datetime) -> bool:
        with self._lock:
            before = self._beat(player, now)
            self._beats[player] = (now, activity)
            if player not in self._online:
                self._online.add(player)
                return True
            return before is None or before[1] != activity

    def state(self, player: str, now: datetime) -> PresenceState:
        with self._lock:
            if not self._is_online(player, now):
                return PresenceState(online=False)
            beat = self._beat(player, now)
            return PresenceState(online=True, activity=beat[1] if beat else None)

    def settle(self, now: datetime) -> list[str]:
        """The players whose presence changed by itself: gone offline, or out of the game (still on the site)."""
        changed: list[str] = []
        with self._lock:
            for player in sorted(self._online):
                beat = self._beats.get(player)
                expired = beat is not None and now - beat[0] >= self.ttl
                if expired:
                    del self._beats[player]
                if not self._is_online(player, now):
                    self._online.discard(player)
                    self._closed_at.pop(player, None)
                    changed.append(player)
                elif expired and beat is not None and beat[1] is not None:
                    changed.append(player)
        return changed
