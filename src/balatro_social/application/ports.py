"""What the use cases need from the outside world."""

from __future__ import annotations

import builtins
from collections.abc import Iterable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from balatro_social.domain import (
    Activity,
    Block,
    Conversation,
    FriendRequest,
    Friendship,
    Member,
    Message,
    PlayerRecord,
    RunCard,
)

from .dto import Event, Player

Box = Literal["incoming", "outgoing", "all"]


class Unit(Protocol):
    """One transaction on the store: everything done in it happens together or not at all.
    ``lock``: keep the rows for this transaction (others wait)."""

    # players
    def player(self, player_id: str, lock: bool = False) -> PlayerRecord | None: ...

    def players(self, ids: Iterable[str]) -> dict[str, PlayerRecord]: ...

    def add_player(self, p: PlayerRecord) -> bool:
        """Stores a new player; False if one with this id is there already."""
        ...

    def save_player(self, p: PlayerRecord) -> None: ...

    def player_by_code(self, code: str) -> PlayerRecord | None: ...

    def find_players(self, query: str, limit: int) -> builtins.list[PlayerRecord]:
        """Players whose name starts with ``query`` (case ignored), by name."""
        ...

    # friends
    def friendship(self, player: str, friend: str) -> Friendship | None: ...

    def friends_of(self, player: str) -> builtins.list[Friendship]: ...

    def count_friends(self, player: str) -> int: ...

    def add_friendship(self, a: str, b: str, since: datetime) -> None:
        """Both sides of it."""
        ...

    def remove_friendship(self, a: str, b: str) -> bool: ...

    # friend requests
    def request(self, request_id: str, lock: bool = False) -> FriendRequest | None: ...

    def pending_between(self, a: str, b: str, lock: bool = False) -> FriendRequest | None:
        """The pending request from either to the other (there is at most one)."""
        ...

    def requests_of(self, player: str, box: Box) -> builtins.list[FriendRequest]:
        """The pending requests to the player (incoming), from them (outgoing) or both; newest first."""
        ...

    def count_pending_from(self, sender: str) -> int: ...

    def count_requests_since(self, sender: str, since: datetime) -> int: ...

    def add_request(self, r: FriendRequest) -> None: ...

    def save_request(self, r: FriendRequest) -> None: ...

    # blocks
    def block(self, blocker: str, blocked: str) -> Block | None: ...

    def blocks_of(self, blocker: str) -> builtins.list[Block]:
        """Newest first."""
        ...

    def add_block(self, b: Block) -> None: ...

    def remove_block(self, blocker: str, blocked: str) -> bool: ...

    # conversations and their members
    def conversation(self, conversation_id: str, lock: bool = False) -> Conversation | None: ...

    def conversations(self, ids: Iterable[str]) -> dict[str, Conversation]: ...

    def direct_between(self, a: str, b: str) -> Conversation | None: ...

    def directs_of(self, player: str) -> dict[str, str]:
        """The player's direct conversations: the other player's id -> the conversation's id."""
        ...

    def add_conversation(self, c: Conversation) -> None: ...

    def save_conversation(self, c: Conversation) -> None: ...

    def member(self, conversation_id: str, player: str) -> Member | None: ...

    def members(self, conversation_ids: Sequence[str]) -> dict[str, builtins.list[Member]]:
        """The players in these conversations now (not those who left), by when they joined."""
        ...

    def memberships(self, player: str) -> builtins.list[Member]:
        """The conversations the player is in now."""
        ...

    def save_member(self, m: Member) -> None:
        """Adds the member, or changes them (a player who left a group and is added again)."""
        ...

    def count_groups(self, player: str) -> int: ...

    # messages
    def add_message(self, m: Message) -> None: ...

    def save_message(self, m: Message) -> None: ...

    def message(self, message_id: str) -> Message | None: ...

    def messages(self, conversation_id: str, floor: int, before: int | None, after: int | None,
                 limit: int) -> builtins.list[Message]:
        """Messages after ``floor``, oldest first: the last ``limit`` before ``before`` (or the last ones), or
        the first ``limit`` after ``after``."""
        ...

    def last_messages(self, conversation_ids: Sequence[str]) -> dict[str, Message]: ...

    def unread(self, player: str, members: Sequence[Member]) -> dict[str, int]:
        """For each of the player's memberships: messages from others after both its last read message and
        its first readable one, not deleted."""
        ...

    def count_messages_since(self, sender: str, since: datetime) -> int: ...


class Store(Protocol):
    def unit(self) -> AbstractContextManager[Unit]: ...


class RunSource(Protocol):
    """The game API: one of the player's runs, read with their own token."""

    def run(self, player: Player, run_id: str) -> RunCard:
        """Raises RunNotFound (not theirs) and GameApiUnavailable."""
        ...


class Subscription(Protocol):
    """One open event stream of a player."""

    async def next(self, timeout: float) -> Event | None:
        """The next event, or None when nothing came in ``timeout`` seconds. Raises EOFError once closed (the
        hub closes a stream that doesn't keep up)."""
        ...

    def close(self) -> None: ...


class EventHub(Protocol):
    def publish(self, players: Iterable[str], event: Event) -> None:
        """To every open stream of these players (from any thread)."""
        ...

    def subscribe(self, player: str) -> Subscription:
        """A new stream (called on the event loop that will read it)."""
        ...


@dataclass(frozen=True)
class PresenceState:
    online: bool
    activity: Activity | None = None


class Presence(Protocol):
    """Who is online: an open event stream, or the game's heartbeat in the last PRESENCE_TTL; and what the game
    says they do. The use cases tell friends when it changes."""

    def connect(self, player: str, now: datetime) -> bool:
        """A stream opened; True if the player just came online."""
        ...

    def disconnect(self, player: str, now: datetime) -> None: ...

    def beat(self, player: str, activity: Activity | None, now: datetime) -> bool:
        """The game's heartbeat; True if the player just came online or does something else now."""
        ...

    def state(self, player: str, now: datetime) -> PresenceState: ...

    def settle(self, now: datetime) -> list[str]:
        """The players who have gone offline since they were last seen online (their last stream closed a few
        seconds ago, and the game's heartbeat stopped): once each."""
        ...


class Authenticator(Protocol):
    @property
    def required(self) -> bool: ...

    def authenticate(self, token: str | None) -> Player: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new_id(self) -> str: ...


class CodeSource(Protocol):
    def code(self) -> str:
        """A new friend code (the system's randomness: nobody can guess the next one)."""
        ...
