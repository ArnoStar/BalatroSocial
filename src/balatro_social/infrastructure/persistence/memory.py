"""Everything kept in memory (lost when the service stops), for tests and demos.

A unit holds the store's lock and works on a copy of the state, which replaces
the state only when the unit ends without an error: all or nothing, as a
database transaction. Records are copied on the way in and out, so a caller
never changes the state without saving."""

from __future__ import annotations

import builtins
import copy
import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime

from balatro_social.domain import (
    Block,
    Conversation,
    ConversationKind,
    FriendRequest,
    Friendship,
    Invite,
    Member,
    Message,
    PlayerRecord,
    RequestStatus,
    pair_key,
)


@dataclass
class _State:
    players: dict[str, PlayerRecord] = field(default_factory=dict)
    friendships: dict[tuple[str, str], Friendship] = field(default_factory=dict)  # (player, friend)
    requests: dict[str, FriendRequest] = field(default_factory=dict)
    blocks: dict[tuple[str, str], Block] = field(default_factory=dict)  # (blocker, blocked)
    conversations: dict[str, Conversation] = field(default_factory=dict)
    members: dict[tuple[str, str], Member] = field(default_factory=dict)  # (conversation, player)
    messages: dict[str, Message] = field(default_factory=dict)
    by_conversation: dict[str, list[str]] = field(default_factory=dict)  # message ids, in order
    avatars: dict[str, tuple[str, bytes]] = field(default_factory=dict)
    invites: dict[str, Invite] = field(default_factory=dict)

    def copy(self) -> _State:
        return _State(dict(self.players), dict(self.friendships), dict(self.requests), dict(self.blocks),
                      dict(self.conversations), dict(self.members), dict(self.messages),
                      {k: list(v) for k, v in self.by_conversation.items()}, dict(self.avatars), dict(self.invites))


def _c[T](x: T) -> T:
    return copy.copy(x)


class MemoryUnit:
    def __init__(self, state: _State) -> None:
        self.s = state

    # players
    def player(self, player_id: str, lock: bool = False) -> PlayerRecord | None:
        p = self.s.players.get(player_id)
        return _c(p) if p else None

    def players(self, ids: Iterable[str]) -> dict[str, PlayerRecord]:
        return {i: _c(self.s.players[i]) for i in set(ids) if i in self.s.players}

    def add_player(self, p: PlayerRecord) -> bool:
        if p.id in self.s.players:
            return False
        self.s.players[p.id] = _c(p)
        return True

    def save_player(self, p: PlayerRecord) -> None:
        self.s.players[p.id] = _c(p)

    def player_by_code(self, code: str) -> PlayerRecord | None:
        return next((_c(p) for p in self.s.players.values() if p.code == code), None)

    def find_players(self, query: str, limit: int) -> builtins.list[PlayerRecord]:
        q = query.lower()
        found = [p for p in self.s.players.values() if p.name and p.name.lower().startswith(q)]
        return [_c(p) for p in sorted(found, key=lambda p: ((p.name or "").lower(), p.id))[:limit]]

    def avatar(self, player: str) -> tuple[str, bytes] | None:
        return self.s.avatars.get(player)

    def save_avatar(self, player: str, content_type: str, data: bytes) -> None:
        self.s.avatars[player] = (content_type, bytes(data))

    def remove_avatar(self, player: str) -> None:
        self.s.avatars.pop(player, None)

    # friends
    def friendship(self, player: str, friend: str) -> Friendship | None:
        return self.s.friendships.get((player, friend))

    def friends_of(self, player: str) -> builtins.list[Friendship]:
        return [f for (p, _), f in self.s.friendships.items() if p == player]

    def count_friends(self, player: str) -> int:
        return len(self.friends_of(player))

    def add_friendship(self, a: str, b: str, since: datetime) -> None:
        self.s.friendships[(a, b)] = Friendship(player=a, friend=b, since=since)
        self.s.friendships[(b, a)] = Friendship(player=b, friend=a, since=since)

    def remove_friendship(self, a: str, b: str) -> bool:
        found = (a, b) in self.s.friendships
        self.s.friendships.pop((a, b), None)
        self.s.friendships.pop((b, a), None)
        return found

    # friend requests
    def request(self, request_id: str, lock: bool = False) -> FriendRequest | None:
        r = self.s.requests.get(request_id)
        return _c(r) if r else None

    def pending_between(self, a: str, b: str, lock: bool = False) -> FriendRequest | None:
        return next((_c(r) for r in self.s.requests.values() if r.status is RequestStatus.PENDING
                     and {r.sender, r.recipient} == {a, b}), None)

    def requests_of(self, player: str, box: str) -> builtins.list[FriendRequest]:
        def mine(r: FriendRequest) -> bool:
            return ((box in ("incoming", "all") and r.recipient == player)
                    or (box in ("outgoing", "all") and r.sender == player))
        found = [r for r in self.s.requests.values() if r.status is RequestStatus.PENDING and mine(r)]
        return [_c(r) for r in sorted(found, key=lambda r: (r.created_at, r.id), reverse=True)]

    def count_pending_from(self, sender: str) -> int:
        return sum(1 for r in self.s.requests.values() if r.sender == sender and r.status is RequestStatus.PENDING)

    def count_requests_since(self, sender: str, since: datetime) -> int:
        return sum(1 for r in self.s.requests.values() if r.sender == sender and r.created_at > since)

    def add_request(self, r: FriendRequest) -> None:
        self.s.requests[r.id] = _c(r)

    def save_request(self, r: FriendRequest) -> None:
        self.s.requests[r.id] = _c(r)

    # blocks
    def block(self, blocker: str, blocked: str) -> Block | None:
        return self.s.blocks.get((blocker, blocked))

    def blocks_of(self, blocker: str) -> builtins.list[Block]:
        return sorted((b for b in self.s.blocks.values() if b.blocker == blocker), key=lambda b: b.at, reverse=True)

    def add_block(self, b: Block) -> None:
        self.s.blocks.setdefault((b.blocker, b.blocked), b)

    def remove_block(self, blocker: str, blocked: str) -> bool:
        return self.s.blocks.pop((blocker, blocked), None) is not None

    # conversations and their members
    def conversation(self, conversation_id: str, lock: bool = False) -> Conversation | None:
        c = self.s.conversations.get(conversation_id)
        return _c(c) if c else None

    def conversations(self, ids: Iterable[str]) -> dict[str, Conversation]:
        return {i: _c(self.s.conversations[i]) for i in set(ids) if i in self.s.conversations}

    def direct_between(self, a: str, b: str, lock: bool = False) -> Conversation | None:
        key = pair_key(a, b)
        return next((_c(c) for c in self.s.conversations.values() if c.pair == key), None)

    def directs_of(self, player: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for c in self.s.conversations.values():
            if c.kind is ConversationKind.DIRECT and c.pair:
                a, b = c.pair.split("|")
                if player in (a, b):
                    out[b if a == player else a] = c.id
        return out

    def add_conversation(self, c: Conversation) -> None:
        self.s.conversations[c.id] = _c(c)
        self.s.by_conversation.setdefault(c.id, [])

    def save_conversation(self, c: Conversation) -> None:
        self.s.conversations[c.id] = _c(c)

    def member(self, conversation_id: str, player: str) -> Member | None:
        m = self.s.members.get((conversation_id, player))
        return _c(m) if m else None

    def members(self, conversation_ids: Sequence[str]) -> dict[str, builtins.list[Member]]:
        wanted = set(conversation_ids)
        out: dict[str, list[Member]] = {}
        for (cid, _), m in sorted(self.s.members.items(), key=lambda kv: (kv[1].joined_at, kv[1].player)):
            if cid in wanted and m.active:
                out.setdefault(cid, []).append(_c(m))
        return out

    def memberships(self, player: str) -> builtins.list[Member]:
        return [_c(m) for (_, p), m in self.s.members.items() if p == player and m.active]

    def save_member(self, m: Member) -> None:
        self.s.members[(m.conversation, m.player)] = _c(m)

    def count_groups(self, player: str) -> int:
        return sum(1 for m in self.memberships(player)
                   if self.s.conversations[m.conversation].kind is ConversationKind.GROUP)

    # messages
    def add_message(self, m: Message) -> None:
        self.s.messages[m.id] = copy.deepcopy(m)
        self.s.by_conversation.setdefault(m.conversation, []).append(m.id)

    def save_message(self, m: Message) -> None:
        self.s.messages[m.id] = copy.deepcopy(m)

    def message(self, message_id: str) -> Message | None:
        m = self.s.messages.get(message_id)
        return copy.deepcopy(m) if m else None

    def _all(self, conversation_id: str) -> builtins.list[Message]:
        return [self.s.messages[i] for i in self.s.by_conversation.get(conversation_id, [])]

    def messages(self, conversation_id: str, floor: int, before: int | None, after: int | None,
                 limit: int) -> builtins.list[Message]:
        msgs = [m for m in self._all(conversation_id) if m.seq > floor]
        if after is not None:
            picked = [m for m in msgs if m.seq > after][:limit]
        else:
            picked = [m for m in msgs if before is None or m.seq < before][-limit:]
        return [copy.deepcopy(m) for m in picked]

    def last_messages(self, conversation_ids: Sequence[str]) -> dict[str, Message]:
        out: dict[str, Message] = {}
        for cid in conversation_ids:
            msgs = self._all(cid)
            if msgs:
                out[cid] = copy.deepcopy(msgs[-1])
        return out

    def unread(self, player: str, members: Sequence[Member]) -> dict[str, int]:
        out: dict[str, int] = {}
        for m in members:
            after = max(m.last_read, m.since_seq)
            n = sum(1 for x in self._all(m.conversation)
                    if x.seq > after and x.sender is not None and x.sender != player and x.deleted_at is None)
            if n:
                out[m.conversation] = n
        return out

    def count_messages_since(self, sender: str, since: datetime) -> int:
        return sum(1 for m in self.s.messages.values() if m.sender == sender and m.created_at > since)


    # invites
    def invite(self, invite_id: str, lock: bool = False) -> Invite | None:
        i = self.s.invites.get(invite_id)
        return _c(i) if i else None

    def open_invite(self, sender: str, recipient: str, code: str, now: datetime, lock: bool = False) -> Invite | None:
        found = [i for i in self.s.invites.values()
                 if i.sender == sender and i.recipient == recipient and i.code == code and i.open(now)]
        return _c(found[0]) if found else None

    def invites_to(self, player: str, now: datetime) -> builtins.list[Invite]:
        mine = [i for i in self.s.invites.values() if i.recipient == player and i.open(now)]
        return [_c(i) for i in sorted(mine, key=lambda i: (i.updated_at, i.id), reverse=True)]

    def count_invites_since(self, sender: str, since: datetime) -> int:
        return sum(1 for i in self.s.invites.values() if i.sender == sender and i.created_at > since)

    def add_invite(self, i: Invite) -> None:
        self.s.invites[i.id] = _c(i)

    def save_invite(self, i: Invite) -> None:
        self.s.invites[i.id] = _c(i)


class MemoryStore:
    def __init__(self) -> None:
        self._state = _State()
        self._lock = threading.RLock()

    @contextmanager
    def unit(self) -> Iterator[MemoryUnit]:
        with self._lock:
            work = self._state.copy()
            yield MemoryUnit(work)
            self._state = work
