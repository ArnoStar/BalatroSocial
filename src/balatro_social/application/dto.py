"""What the use cases take and return: the HTTP API's contract (field names are the JSON names)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from balatro_social.domain import (
    ActivityKind,
    ConversationKind,
    MessageKind,
    RequestPolicy,
    RequestStatus,
    SystemEvent,
)

Relation = Literal["you", "friend", "incoming", "outgoing", "blocked", "none"]
"""How a player is related to the caller: a friend, a friend request waiting for the caller's answer
(incoming) or theirs (outgoing), a player the caller blocked."""


@dataclass(frozen=True, kw_only=True)
class Player:
    """The caller, from their access token."""

    id: str
    name: str | None = None
    roles: frozenset[str] = frozenset()
    token: str | None = None  # (the game API is read with it, as them)
    expires_at: datetime | None = None  # when the token expires: an event stream ends then


@dataclass(frozen=True, kw_only=True)
class PlayerRef:
    id: str
    name: str | None
    # their profile picture's version: GET /v1/avatars/{id}?v=<avatar> (None: none, show their initials)
    avatar: int | None = None


@dataclass(frozen=True, kw_only=True)
class ActivityView:
    kind: ActivityKind  # menu (between runs), run, watching (a run again)
    deck: str | None = None  # a run's deck (b_red ...), stake (1-8) and ante
    stake: int | None = None
    ante: int | None = None
    seeded: bool = False
    challenge: str | None = None


@dataclass(frozen=True, kw_only=True)
class PresenceView:
    """Only friends see it (and only if the player shows it): others see everyone offline."""

    online: bool
    activity: ActivityView | None = None  # what they do in the game (None: not in the game, or not online)
    last_seen: datetime | None = None  # when they were last online (when they aren't)


@dataclass(frozen=True, kw_only=True)
class PlayerView:
    id: str
    name: str | None
    relation: Relation
    avatar: int | None = None  # their profile picture's version: GET /v1/avatars/{id}?v=<avatar>
    request: str | None = None  # the friend request waiting between you (incoming or outgoing)
    presence: PresenceView | None = None  # friends'
    since: datetime | None = None  # friends since
    conversation: str | None = None  # your direct conversation, if there is one


@dataclass(frozen=True, kw_only=True)
class RequestView:
    id: str
    sender: PlayerRef
    recipient: PlayerRef
    status: RequestStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, kw_only=True)
class MeView:
    id: str
    name: str | None
    friend_code: str  # ABCD-2345: others add you with it (an invite link: <site>/friends/add/<code>)
    avatar: int | None  # your profile picture's version (GET /v1/avatars/{id}?v=<avatar>), None: none
    requests: RequestPolicy  # who may send you a friend request: everyone, or only with your code
    show_presence: bool  # your friends see when you are online and what you play
    friends: int
    incoming: int  # friend requests waiting for your answer
    unread: int  # messages you haven't read (muted conversations aside)


@dataclass(frozen=True, kw_only=True)
class RunCardView:
    """A run as it was when it was shared."""

    id: str  # the run's id in the game API: /play/?watch=<id> watches it once it is finished
    deck: str
    stake: int
    seed: str
    seeded: bool  # its player chose the seed
    challenge: str | None
    ante: int
    round: int
    won: bool
    finished: bool
    best_hand: float  # the run's best single hand
    counted: bool  # it counts for stats and leaderboards (not seeded, no challenge)
    played_at: datetime


@dataclass(frozen=True, kw_only=True)
class SeedCardView:
    """A seed to play: /play/?seed=<seed>&deck=<deck>&stake=<stake> opens the run setup with it."""

    seed: str
    deck: str
    stake: int


@dataclass(frozen=True, kw_only=True)
class SystemView:
    """What happened in a group."""

    event: SystemEvent
    by: PlayerRef | None
    players: list[PlayerRef] = field(default_factory=list)  # who was added, removed, or left
    title: str | None = None  # the new title (created, renamed)


@dataclass(frozen=True, kw_only=True)
class MessageView:
    id: str
    conversation: str
    seq: int  # 1, 2, ... in its conversation
    sender: PlayerRef | None  # None: a system message
    kind: MessageKind
    text: str  # a text message's, or the note with a run or a seed ("" when deleted)
    created_at: datetime
    deleted: bool = False
    run: RunCardView | None = None
    seed: SeedCardView | None = None
    system: SystemView | None = None


@dataclass(frozen=True, kw_only=True)
class MemberView:
    id: str
    name: str | None
    avatar: int | None
    owner: bool
    last_read: int  # the last message they have read (read receipts)


@dataclass(frozen=True, kw_only=True)
class ConversationView:
    id: str
    kind: ConversationKind
    title: str | None  # a group's
    owner: str | None  # a group's owner: renames and removes members
    members: list[MemberView]  # the players in it now, you included
    last_seq: int
    last_message: MessageView | None
    unread: int  # messages from others after your last read one
    muted: bool  # (yours: unread messages of a muted conversation don't count in /v1/me's unread)
    can_send: bool  # false: a direct conversation with someone who isn't your friend any more
    created_at: datetime
    updated_at: datetime  # its last message's time (or when it was made)


@dataclass(frozen=True, kw_only=True)
class ReadView:
    conversation: str
    player: str
    seq: int


@dataclass(frozen=True, kw_only=True)
class TypingView:
    conversation: str
    player: PlayerRef


@dataclass(frozen=True, kw_only=True)
class PresenceEvent:
    player: str
    presence: PresenceView


@dataclass(frozen=True, kw_only=True)
class Gone:
    """Something the client should drop: a conversation left, a friend removed."""

    id: str


@dataclass(frozen=True, kw_only=True)
class AvatarImage:
    content_type: str
    data: bytes
    version: int


@dataclass(frozen=True)
class Event:
    """A change a player's clients should know about at once (docs/events.md): ``data`` is a view."""

    type: str
    data: Any


# ------------------------------------------------------------------ input


@dataclass(frozen=True, kw_only=True)
class MeChanges:
    requests: RequestPolicy | None = None
    show_presence: bool | None = None


@dataclass(frozen=True, kw_only=True)
class NewRequest:
    """To a player by id, or by their friend code."""

    to: str | None = None
    code: str | None = None


@dataclass(frozen=True, kw_only=True)
class NewGroup:
    title: str
    members: tuple[str, ...]  # friends of yours


@dataclass(frozen=True, kw_only=True)
class ConversationChanges:
    title: str | None = None  # (groups)
    muted: bool | None = None  # (yours)


@dataclass(frozen=True, kw_only=True)
class SeedInput:
    seed: str
    deck: str
    stake: int


@dataclass(frozen=True, kw_only=True)
class NewMessage:
    """A text, or a run (one of yours, by its id in the game API) or a seed, with an optional note."""

    text: str | None = None
    run: str | None = None
    seed: SeedInput | None = None


@dataclass(frozen=True, kw_only=True)
class ActivityInput:
    kind: ActivityKind
    deck: str | None = None
    stake: int | None = None
    ante: int | None = None
    seeded: bool = False
    challenge: str | None = None
