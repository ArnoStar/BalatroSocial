"""Stand-ins for the game API, the clock, ids and codes, and a hub that keeps what it published."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from balatro_social.application.dto import Event, Player
from balatro_social.application.errors import GameApiUnavailable, NoOpenMatch, RunNotFound
from balatro_social.domain import MatchCard, RunCard
from balatro_social.infrastructure.hub import LocalHub

T0 = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self, t: datetime = T0) -> None:
        self.t = t

    def now(self) -> datetime:
        return self.t

    def advance(self, **kw: float) -> None:
        self.t += timedelta(**kw)


class Ids:
    def __init__(self) -> None:
        self.n = 0

    def new_id(self) -> str:
        self.n += 1
        return f"id{self.n:04d}"


class Codes:
    """Codes in order (AAAA2222, AAAA2223 ...), with the first one twice: a code already taken is drawn again."""

    def __init__(self) -> None:
        self.n = -1

    def code(self) -> str:
        self.n += 1
        digits = "23456789"
        k = max(0, self.n - 1)
        return "AAAA" + "".join(digits[(k // 8 ** i) % 8] for i in (3, 2, 1, 0))


class FakeRuns:
    """The game API: runs to share, and the players' matches waiting for players."""

    def __init__(self) -> None:
        self.cards: dict[tuple[str, str], RunCard] = {}
        self.matches: dict[str, MatchCard] = {}
        self.down = False
        self.calls = 0

    def open_match(self, player: Player) -> MatchCard:
        if self.down:
            raise GameApiUnavailable("down")
        m = self.matches.get(player.id)
        if m is None:
            raise NoOpenMatch()
        return m

    def add(self, player: str, run_id: str, **kw: object) -> RunCard:
        values: dict[str, object] = {"deck": "b_red", "stake": 1, "seed": "ABCD1234", "seeded": False,
                                     "challenge": None, "ante": 8, "round": 24, "won": True, "finished": True,
                                     "best_hand": 123456.0, "counted": True, "played_at": T0}
        values.update(kw)
        card = RunCard(id=run_id, **values)  # type: ignore[arg-type]
        self.cards[(player, run_id)] = card
        return card

    def run(self, player: Player, run_id: str) -> RunCard:
        self.calls += 1
        if self.down:
            raise GameApiUnavailable("down")
        card = self.cards.get((player.id, run_id))
        if card is None:
            raise RunNotFound(run_id)
        return card


class RecordingHub(LocalHub):
    """The real hub, keeping a copy of every event it publishes."""

    def __init__(self) -> None:
        super().__init__()
        self.published: list[tuple[list[str], Event]] = []

    def publish(self, players: Iterable[str], event: Event) -> None:
        to = list(players)
        self.published.append((to, event))
        super().publish(to, event)

    def to(self, player: str, type: str | None = None) -> list[Event]:
        return [e for ps, e in self.published if player in ps and (type is None or e.type == type)]

    def clear(self) -> None:
        self.published.clear()
