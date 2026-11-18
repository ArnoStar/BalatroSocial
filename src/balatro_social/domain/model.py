"""What the social service keeps: players, their friendships, requests and
blocks, conversations (direct and group) and their messages, and invites to
play a match together."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

ANONYMOUS_PLAYER = "anonymous"


class RequestPolicy(StrEnum):
    """Who may send the player a friend request."""

    EVERYONE = "everyone"
    CODE = "code"  # only with the player's friend code (an invite link)


@dataclass
class PlayerRecord:
    """A player as this service knows them: made the first time they come, named after their account."""

    id: str
    name: str | None
    code: str  # the friend code (an invite link carries it): 8 characters of CODE_ALPHABET
    created_at: datetime
    requests: RequestPolicy = RequestPolicy.EVERYONE
    show_presence: bool = True  # friends see when they are online and what they play
    last_seen: datetime | None = None
    avatar: int = 0  # the profile picture's version (when it was set, ms since the epoch); 0: none


class RequestStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"


@dataclass
class FriendRequest:
    id: str
    sender: str
    recipient: str
    status: RequestStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Friendship:
    """One side of a friendship (each friendship is kept as two: one per player)."""

    player: str
    friend: str
    since: datetime


@dataclass(frozen=True)
class Block:
    blocker: str
    blocked: str
    at: datetime


class ConversationKind(StrEnum):
    DIRECT = "direct"  # two friends
    GROUP = "group"  # up to MAX_GROUP_MEMBERS players, with a title and an owner


@dataclass
class Conversation:
    id: str
    kind: ConversationKind
    created_at: datetime
    title: str | None = None  # a group's
    owner: str | None = None  # a group's (it renames it and removes members)
    pair: str | None = None  # a direct conversation's players (pair_key): one conversation per pair
    last_seq: int = 0  # the last message's number (messages are numbered 1, 2, ... in a conversation)
    last_at: datetime | None = None  # when the last message was sent


@dataclass
class Member:
    conversation: str
    player: str
    joined_at: datetime
    since_seq: int = 0  # the messages after this one are theirs to read (a group's history before they joined isn't)
    last_read: int = 0  # the last message they have read
    muted: bool = False
    left_at: datetime | None = None  # (only groups can be left)

    @property
    def active(self) -> bool:
        return self.left_at is None


class SystemEvent(StrEnum):
    """What a system message says happened in a group."""

    CREATED = "created"
    RENAMED = "renamed"
    ADDED = "added"
    REMOVED = "removed"
    LEFT = "left"


class MessageKind(StrEnum):
    TEXT = "text"
    RUN = "run"  # a run shared from the game API (a RunCard in ``attachment``)
    SEED = "seed"  # a seed to play (a SeedCard in ``attachment``)
    SYSTEM = "system"  # what happened in a group: made, renamed, joined, left (``attachment``: event, players)


@dataclass
class Message:
    id: str
    conversation: str
    seq: int
    sender: str | None  # None: a system message
    kind: MessageKind
    text: str
    created_at: datetime
    attachment: dict[str, Any] | None = None
    deleted_at: datetime | None = None


@dataclass(frozen=True)
class RunCard:
    """A run as it was when it was shared (the game API's summary, read with the sharer's token)."""

    id: str
    deck: str
    stake: int
    seed: str
    seeded: bool
    challenge: str | None
    ante: int
    round: int
    won: bool
    finished: bool
    best_hand: float
    counted: bool
    played_at: datetime

    def to_json(self) -> dict[str, Any]:
        return {**asdict(self), "played_at": self.played_at.isoformat()}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> RunCard:
        return cls(**{**d, "played_at": datetime.fromisoformat(d["played_at"])})


@dataclass(frozen=True)
class SeedCard:
    """A seed to play, with the deck and stake it was played with."""

    seed: str
    deck: str
    stake: int

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> SeedCard:
        return cls(seed=str(d["seed"]), deck=str(d["deck"]), stake=int(d["stake"]))


class ActivityKind(StrEnum):
    MENU = "menu"  # in the game, between runs
    RUN = "run"  # playing a run
    WATCHING = "watching"  # watching a run again


@dataclass(frozen=True)
class Activity:
    """What the game says the player is doing (with its heartbeat)."""

    kind: ActivityKind
    deck: str | None = None
    stake: int | None = None
    ante: int | None = None
    seeded: bool = False
    challenge: str | None = None
    mode: str | None = None  # a multiplayer run: "pvp" or "coop"


class InviteStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"


@dataclass
class Invite:
    """A player invites a friend to their multiplayer match (its lobby on the game API): the friend joins it with
    ``code``. It is open until answered or until ``expires_at``."""

    id: str
    sender: str
    recipient: str
    mode: str  # the match's mode ("pvp", "coop")
    code: str  # the match's invite code
    match: str  # the match's id
    status: InviteStatus
    created_at: datetime
    expires_at: datetime
    updated_at: datetime

    def open(self, now: datetime) -> bool:
        return self.status is InviteStatus.PENDING and now < self.expires_at


@dataclass(frozen=True)
class MatchCard:
    """A player's match waiting for players, as the game API says (read with their own token)."""

    id: str
    code: str
    mode: str
