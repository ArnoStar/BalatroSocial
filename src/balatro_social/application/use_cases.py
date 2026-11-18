"""The use cases: one class each, taking the caller (``Player``) first.

A friendship starts only when both players want it (a request accepted, or two
requests crossing). Direct messages go between friends; a group's members are
friends of whoever added them; invites to a match go to friends. Presence is
for friends only. Every change
happens in one store transaction (``Unit``), and its events go out once the
transaction is done (``Outbox``)."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from balatro_social.domain import (
    INVITE_TTL,
    INVITES_PER_HOUR,
    MAX_AVATAR_LOOKUP,
    MAX_FRIENDS,
    MAX_GROUP_MEMBERS,
    MAX_GROUPS,
    MAX_PENDING_SENT,
    MESSAGE_BURST,
    MESSAGE_WINDOW,
    REQUESTS_PER_DAY,
    Activity,
    AlreadyFriends,
    AvatarNotFound,
    Block,
    CantAdd,
    CantMessage,
    CodeNotFound,
    Conversation,
    ConversationKind,
    ConversationNotFound,
    FriendRequest,
    GroupFull,
    InvalidMessage,
    Invite,
    InviteClosed,
    InviteNotFound,
    InviteStatus,
    Member,
    Message,
    MessageKind,
    MessageNotFound,
    NotAGroup,
    NotFriends,
    NotOwner,
    PlayerNotFound,
    PlayerRecord,
    RequestClosed,
    RequestNotFound,
    RequestPolicy,
    RequestStatus,
    RunCard,
    SeedCard,
    SelfAction,
    SlowDown,
    SystemEvent,
    TooManyFriends,
    TooManyGroups,
    TooManyRequests,
    check_activity,
    check_avatar,
    check_seed,
    clean_note,
    clean_text,
    clean_title,
    pair_key,
    parse_code,
    show_code,
)

from .dto import (
    ActivityInput,
    ActivityView,
    AvatarImage,
    ConversationChanges,
    ConversationView,
    Event,
    Gone,
    InboxView,
    InviteView,
    MeChanges,
    MemberView,
    MessageView,
    MeView,
    NewGroup,
    NewInvite,
    NewMessage,
    NewRequest,
    Player,
    PlayerRef,
    PlayerView,
    PresenceEvent,
    PresenceView,
    ReadView,
    Relation,
    RequestView,
    RunCardView,
    SeedCardView,
    SystemView,
    TypingView,
)
from .errors import GameApiUnavailable
from .ports import (
    Authenticator,
    Box,
    Clock,
    CodeSource,
    EventHub,
    IdGenerator,
    MatchSource,
    Presence,
    RunSource,
    Store,
    Subscription,
    Unit,
)

log = logging.getLogger(__name__)

SEEN_EVERY = timedelta(seconds=60)  # a player online all along has their last_seen written this often
MAX_PAGE = 100  # messages in one answer
MIN_QUERY = 2  # characters to search players by name


@dataclass(frozen=True)
class Deps:
    store: Store
    runs: RunSource
    hub: EventHub
    presence: Presence
    clock: Clock
    ids: IdGenerator
    codes: CodeSource
    matches: MatchSource | None = None  # (None: invites can't be sent)


class Outbox:
    """The events of a transaction: sent once it is done (none when it fails)."""

    def __init__(self) -> None:
        self.events: list[tuple[tuple[str, ...], Event]] = []

    def add(self, players: Iterable[str], type: str, data: Any) -> None:
        to = tuple(dict.fromkeys(players))
        if to:
            self.events.append((to, Event(type, data)))

    def send(self, hub: EventHub) -> None:
        for to, event in self.events:
            hub.publish(to, event)


# ------------------------------------------------------------------ helpers


def new_code(deps: Deps, u: Unit) -> str:
    code = deps.codes.code()
    while u.player_by_code(code) is not None:
        code = deps.codes.code()
    return code


def ensure_player(deps: Deps, u: Unit, player: Player, now: datetime) -> PlayerRecord:
    """The caller's record, made the first time; their name follows their account's."""
    rec = u.player(player.id)
    if rec is None:
        rec = PlayerRecord(id=player.id, name=player.name, code=new_code(deps, u), created_at=now)
        if not u.add_player(rec):  # (another request made it at the same time)
            rec = u.player(player.id)
            assert rec is not None
    elif player.name and player.name != rec.name:
        rec.name = player.name
        u.save_player(rec)
    return rec


def existing(u: Unit, player_id: str) -> PlayerRecord:
    rec = u.player(player_id)
    if rec is None:
        raise PlayerNotFound(player_id)
    return rec


def ref(names: dict[str, PlayerRecord], player_id: str) -> PlayerRef:
    rec = names.get(player_id)
    return PlayerRef(id=player_id, name=rec.name if rec else None, avatar=(rec.avatar or None) if rec else None)


def relation(u: Unit, me: str, other: str) -> tuple[Relation, FriendRequest | None]:
    if me == other:
        return "you", None
    if u.block(me, other) is not None:
        return "blocked", None
    if u.friendship(me, other) is not None:
        return "friend", None
    pending = u.pending_between(me, other)
    if pending is None:
        return "none", None
    return ("outgoing" if pending.sender == me else "incoming"), pending


def activity_view(a: Activity | None) -> ActivityView | None:
    if a is None:
        return None
    return ActivityView(kind=a.kind, deck=a.deck, stake=a.stake, ante=a.ante, seeded=a.seeded, challenge=a.challenge,
                        mode=a.mode)


def presence_view(deps: Deps, rec: PlayerRecord, now: datetime) -> PresenceView:
    """What friends see: nothing (offline) if the player hides it."""
    if not rec.show_presence:
        return PresenceView(online=False)
    state = deps.presence.state(rec.id, now)
    if state.online:
        return PresenceView(online=True, activity=activity_view(state.activity))
    return PresenceView(online=False, last_seen=rec.last_seen)


def friend_view(deps: Deps, rec: PlayerRecord, since: datetime, conversation: str | None, now: datetime) -> PlayerView:
    return PlayerView(id=rec.id, name=rec.name, relation="friend", avatar=rec.avatar or None,
                      presence=presence_view(deps, rec, now), since=since, conversation=conversation)


def player_view(deps: Deps, u: Unit, me: str, rec: PlayerRecord, now: datetime) -> PlayerView:
    rel, pending = relation(u, me, rec.id)
    conversation = u.directs_of(me).get(rec.id) if rel != "you" else None
    if rel == "friend":
        f = u.friendship(me, rec.id)
        assert f is not None
        return friend_view(deps, rec, f.since, conversation, now)
    return PlayerView(id=rec.id, name=rec.name, relation=rel, avatar=rec.avatar or None,
                      request=pending.id if pending else None, conversation=conversation)


def me_view(u: Unit, rec: PlayerRecord) -> MeView:
    mine = u.memberships(rec.id)
    unread = u.unread(rec.id, mine)
    return MeView(id=rec.id, name=rec.name, friend_code=show_code(rec.code), avatar=rec.avatar or None,
                  requests=rec.requests,
                  show_presence=rec.show_presence, friends=u.count_friends(rec.id),
                  incoming=len(u.requests_of(rec.id, "incoming")),
                  unread=sum(unread.get(m.conversation, 0) for m in mine if not m.muted))


def request_view(u: Unit, r: FriendRequest) -> RequestView:
    names = u.players([r.sender, r.recipient])
    return RequestView(id=r.id, sender=ref(names, r.sender), recipient=ref(names, r.recipient), status=r.status,
                       created_at=r.created_at, updated_at=r.updated_at)


def mentioned(messages: Iterable[Message]) -> set[str]:
    """The players a view of these messages names: senders, and those of system messages."""
    out: set[str] = set()
    for m in messages:
        if m.sender:
            out.add(m.sender)
        if m.kind is MessageKind.SYSTEM and m.attachment:
            out.update(p for p in m.attachment.get("players", []) if isinstance(p, str))
            if isinstance(m.attachment.get("by"), str):
                out.add(m.attachment["by"])
    return out


def message_view(m: Message, names: dict[str, PlayerRecord]) -> MessageView:
    sender = ref(names, m.sender) if m.sender else None
    base: dict[str, Any] = {"id": m.id, "conversation": m.conversation, "seq": m.seq, "sender": sender,
                            "kind": m.kind, "created_at": m.created_at}
    if m.deleted_at is not None:
        return MessageView(**base, text="", deleted=True)
    a = m.attachment or {}
    if m.kind is MessageKind.RUN and "run" in a:
        card = RunCard.from_json(a["run"])
        return MessageView(**base, text=m.text, run=RunCardView(**vars(card)))
    if m.kind is MessageKind.SEED and "seed" in a:
        seed = SeedCard.from_json(a["seed"])
        return MessageView(**base, text=m.text, seed=SeedCardView(seed=seed.seed, deck=seed.deck, stake=seed.stake))
    if m.kind is MessageKind.SYSTEM:
        by = a.get("by")
        system = SystemView(event=SystemEvent(a.get("event", SystemEvent.CREATED)),
                            by=ref(names, by) if isinstance(by, str) else None,
                            players=[ref(names, p) for p in a.get("players", []) if isinstance(p, str)],
                            title=a.get("title"))
        return MessageView(**base, text="", system=system)
    return MessageView(**base, text=m.text)


def conversation_view(c: Conversation, viewer: Member, members: Sequence[Member], last: Message | None, unread: int,
                      friends: set[str], names: dict[str, PlayerRecord]) -> ConversationView:
    others = [m.player for m in members if m.player != viewer.player]
    can_send = c.kind is ConversationKind.GROUP or (len(others) == 1 and others[0] in friends)
    return ConversationView(
        id=c.id, kind=c.kind, title=c.title, owner=c.owner,
        members=[MemberView(id=m.player, name=ref(names, m.player).name, avatar=ref(names, m.player).avatar,
                            owner=m.player == c.owner, last_read=m.last_read) for m in members],
        last_seq=c.last_seq, last_message=message_view(last, names) if last else None, unread=unread,
        muted=viewer.muted, can_send=can_send, created_at=c.created_at, updated_at=c.last_at or c.created_at)


def one_conversation(u: Unit, c: Conversation, viewer: str) -> ConversationView:
    members = u.members([c.id]).get(c.id, [])
    mine = next((m for m in members if m.player == viewer), None)
    if mine is None:
        raise ConversationNotFound(c.id)
    last = u.last_messages([c.id]).get(c.id)
    friends = {f.friend for f in u.friends_of(viewer)} if c.kind is ConversationKind.DIRECT else set()
    names = u.players({m.player for m in members} | mentioned([last] if last else []))
    return conversation_view(c, mine, members, last, u.unread(viewer, [mine]).get(c.id, 0), friends, names)


def active_players(u: Unit, c: Conversation) -> list[str]:
    return [m.player for m in u.members([c.id]).get(c.id, [])]


def member_of(u: Unit, conversation_id: str, player: str, lock: bool = False) -> tuple[Conversation, Member]:
    """The conversation and the player's membership: others' conversations don't exist for them."""
    c = u.conversation(conversation_id, lock=lock)
    m = u.member(conversation_id, player) if c else None
    if c is None or m is None or not m.active:
        raise ConversationNotFound(conversation_id)
    return c, m


def post(deps: Deps, u: Unit, c: Conversation, now: datetime, sender: str | None, kind: MessageKind, text: str,
         attachment: dict[str, Any] | None = None) -> Message:
    """Adds a message to a conversation read with lock=True (the numbers follow each other)."""
    m = Message(id=deps.ids.new_id(), conversation=c.id, seq=c.last_seq + 1, sender=sender, kind=kind, text=text,
                created_at=now, attachment=attachment)
    u.add_message(m)
    c.last_seq, c.last_at = m.seq, now
    u.save_conversation(c)
    return m


def post_system(deps: Deps, u: Unit, c: Conversation, now: datetime, event: SystemEvent, by: str,
                players: Sequence[str] = (), title: str | None = None) -> Message:
    return post(deps, u, c, now, None, MessageKind.SYSTEM, "",
                {"event": event.value, "by": by, "players": list(players), "title": title})


def tell_conversation(out: Outbox, u: Unit, c: Conversation, viewers: Iterable[str]) -> None:
    """Each viewer's own view of the conversation (unread counts differ)."""
    for p in viewers:
        out.add([p], "conversation", one_conversation(u, c, p))


def tell_message(out: Outbox, u: Unit, c: Conversation, m: Message, type: str = "message") -> MessageView:
    view = message_view(m, u.players(mentioned([m])))
    out.add(active_players(u, c), type, view)
    return view


def announce(out: Outbox, deps: Deps, u: Unit, rec: PlayerRecord, now: datetime) -> None:
    """Tells the player's friends whether they are online and what they do."""
    out.add([f.friend for f in u.friends_of(rec.id)], "presence",
            PresenceEvent(player=rec.id, presence=presence_view(deps, rec, now)))


def befriend(deps: Deps, u: Unit, out: Outbox, r: FriendRequest, now: datetime) -> None:
    """The request's two players become friends."""
    for p in (r.sender, r.recipient):
        if u.count_friends(p) >= MAX_FRIENDS:
            who = "you have" if p == r.recipient else "they have"
            raise TooManyFriends(f"{who} {MAX_FRIENDS} friends already")
    u.add_friendship(r.sender, r.recipient, now)
    r.status, r.updated_at = RequestStatus.ACCEPTED, now
    u.save_request(r)
    out.add([r.sender, r.recipient], "friend_request", request_view(u, r))
    recs = u.players([r.sender, r.recipient])
    for me, other in ((r.sender, r.recipient), (r.recipient, r.sender)):
        out.add([me], "friend", friend_view(deps, recs[other], now, u.directs_of(me).get(other), now))
    c = u.direct_between(r.sender, r.recipient)
    if c is not None:  # (they may write to each other again)
        tell_conversation(out, u, c, [r.sender, r.recipient])


def unfriend(u: Unit, out: Outbox, a: str, b: str) -> bool:
    if not u.remove_friendship(a, b):
        return False
    out.add([a], "friend_removed", Gone(id=b))
    out.add([b], "friend_removed", Gone(id=a))
    c = u.direct_between(a, b)
    if c is not None:  # (it stays, to read, but nobody writes in it any more)
        tell_conversation(out, u, c, [a, b])
    return True


# ------------------------------------------------------------------ the caller


class Authenticate:
    def __init__(self, authenticator: Authenticator) -> None:
        self.authenticator = authenticator

    def __call__(self, token: str | None) -> Player:
        return self.authenticator.authenticate(token)


class _UseCase:
    def __init__(self, deps: Deps) -> None:
        self.deps = deps


class GetMe(_UseCase):
    def __call__(self, player: Player) -> MeView:
        with self.deps.store.unit() as u:
            return me_view(u, ensure_player(self.deps, u, player, self.deps.clock.now()))


class UpdateMe(_UseCase):
    def __call__(self, player: Player, changes: MeChanges) -> MeView:
        now, out = self.deps.clock.now(), Outbox()
        with self.deps.store.unit() as u:
            rec = ensure_player(self.deps, u, player, now)
            shown = rec.show_presence
            if changes.requests is not None:
                rec.requests = changes.requests
            if changes.show_presence is not None:
                rec.show_presence = changes.show_presence
            u.save_player(rec)
            if rec.show_presence != shown and self.deps.presence.state(rec.id, now).online:
                announce(out, self.deps, u, rec, now)  # online again for their friends, or offline
            view = me_view(u, rec)
            out.add([rec.id], "me", view)
        out.send(self.deps.hub)
        return view


class NewFriendCode(_UseCase):
    """A new friend code: the old one (and its invite links) stops working."""

    def __call__(self, player: Player) -> MeView:
        with self.deps.store.unit() as u:
            rec = ensure_player(self.deps, u, player, self.deps.clock.now())
            rec.code = new_code(self.deps, u)
            u.save_player(rec)
            return me_view(u, rec)


class ReportPresence(_UseCase):
    """The game's heartbeat: the player is in the game, doing ``activity``."""

    def __call__(self, player: Player, activity: ActivityInput | None) -> None:
        act = check_activity(Activity(kind=activity.kind, deck=activity.deck, stake=activity.stake,
                                      ante=activity.ante, seeded=activity.seeded,
                                      challenge=activity.challenge, mode=activity.mode)) if activity else None
        now, out = self.deps.clock.now(), Outbox()
        with self.deps.store.unit() as u:
            rec = ensure_player(self.deps, u, player, now)
            changed = self.deps.presence.beat(rec.id, act, now)
            if rec.last_seen is None or now - rec.last_seen >= SEEN_EVERY:
                rec.last_seen = now
                u.save_player(rec)
            if changed and rec.show_presence:
                announce(out, self.deps, u, rec, now)
        out.send(self.deps.hub)


# ------------------------------------------------------------------ players


class FindPlayers(_UseCase):
    """Players by the start of their name. Players who take requests only with their code aren't listed
    (unless they are friends), nor those who blocked the caller."""

    def __call__(self, player: Player, query: str, limit: int = 20) -> list[PlayerView]:
        q = " ".join(query.split())
        if len(q) < MIN_QUERY:
            return []
        now = self.deps.clock.now()
        with self.deps.store.unit() as u:
            me = ensure_player(self.deps, u, player, now)
            out: list[PlayerView] = []
            for rec in u.find_players(q, limit * 3):
                if rec.id == me.id or u.block(rec.id, me.id) is not None:
                    continue
                view = player_view(self.deps, u, me.id, rec, now)
                if rec.requests is RequestPolicy.CODE and view.relation != "friend":
                    continue
                out.append(view)
                if len(out) >= limit:
                    break
            return out


class GetPlayer(_UseCase):
    def __call__(self, player: Player, player_id: str) -> PlayerView:
        now = self.deps.clock.now()
        with self.deps.store.unit() as u:
            me = ensure_player(self.deps, u, player, now)
            return player_view(self.deps, u, me.id, existing(u, player_id), now)


class PlayerByCode(_UseCase):
    """Who a friend code (an invite link) is."""

    def __call__(self, player: Player, code: str) -> PlayerView:
        now = self.deps.clock.now()
        parsed = parse_code(code)
        with self.deps.store.unit() as u:
            me = ensure_player(self.deps, u, player, now)
            rec = u.player_by_code(parsed) if parsed else None
            if rec is None:
                raise CodeNotFound(code)
            return player_view(self.deps, u, me.id, rec, now)


# ------------------------------------------------------------------ friends


class ListFriends(_UseCase):
    """Online first, then by name."""

    def __call__(self, player: Player) -> list[PlayerView]:
        now = self.deps.clock.now()
        with self.deps.store.unit() as u:
            me = ensure_player(self.deps, u, player, now)
            friends = u.friends_of(me.id)
            recs = u.players(f.friend for f in friends)
            directs = u.directs_of(me.id)
            views = [friend_view(self.deps, recs[f.friend], f.since, directs.get(f.friend), now)
                     for f in friends if f.friend in recs]
        views.sort(key=lambda v: (not (v.presence and v.presence.online), (v.name or "").lower(), v.id))
        return views


class RemoveFriend(_UseCase):
    def __call__(self, player: Player, friend: str) -> None:
        out = Outbox()
        with self.deps.store.unit() as u:
            me = ensure_player(self.deps, u, player, self.deps.clock.now())
            if not unfriend(u, out, me.id, friend):
                raise NotFriends(f"{friend!r} isn't your friend")
        out.send(self.deps.hub)


class ListRequests(_UseCase):
    def __call__(self, player: Player, box: Box = "all") -> list[RequestView]:
        with self.deps.store.unit() as u:
            me = ensure_player(self.deps, u, player, self.deps.clock.now())
            return [request_view(u, r) for r in u.requests_of(me.id, box)]


class SendRequest(_UseCase):
    """To a player by id, or by friend code. If they asked first, the two become friends at once."""

    def __call__(self, player: Player, request: NewRequest) -> RequestView:
        now, out = self.deps.clock.now(), Outbox()
        with self.deps.store.unit() as u:
            me = ensure_player(self.deps, u, player, now)
            by_code = request.code is not None
            if request.code is not None:
                code = parse_code(request.code)
                target = u.player_by_code(code) if code else None
                if target is None:
                    raise CodeNotFound(request.code)
            else:
                target = existing(u, request.to or "")
            if target.id == me.id:
                raise SelfAction("you can't be your own friend")
            if u.block(me.id, target.id) is not None:
                raise CantAdd("you blocked this player: unblock them first")
            if u.block(target.id, me.id) is not None:
                raise CantAdd("this player doesn't take friend requests from you")
            if u.friendship(me.id, target.id) is not None:
                raise AlreadyFriends(f"you are friends with {target.name or target.id} already")
            pending = u.pending_between(me.id, target.id, lock=True)
            if pending is not None:
                if pending.recipient == me.id:  # they asked first: both want it
                    befriend(self.deps, u, out, pending, now)
                view = request_view(u, pending)
            else:
                if target.requests is RequestPolicy.CODE and not by_code:
                    raise CantAdd("this player takes friend requests only with their friend code")
                if u.count_friends(me.id) >= MAX_FRIENDS:
                    raise TooManyFriends(f"you have {MAX_FRIENDS} friends already")
                if u.count_pending_from(me.id) >= MAX_PENDING_SENT:
                    raise TooManyRequests(f"{MAX_PENDING_SENT} of your friend requests are waiting for an answer")
                if u.count_requests_since(me.id, now - timedelta(days=1)) >= REQUESTS_PER_DAY:
                    raise TooManyRequests(f"you have sent {REQUESTS_PER_DAY} friend requests today")
                r = FriendRequest(id=self.deps.ids.new_id(), sender=me.id, recipient=target.id,
                                  status=RequestStatus.PENDING, created_at=now, updated_at=now)
                u.add_request(r)
                view = request_view(u, r)
                out.add([me.id, target.id], "friend_request", view)
        out.send(self.deps.hub)
        return view


class _Answer(_UseCase):
    def answer(self, player: Player, request_id: str, as_recipient: bool, status: RequestStatus) -> RequestView:
        now, out = self.deps.clock.now(), Outbox()
        with self.deps.store.unit() as u:
            ensure_player(self.deps, u, player, now)
            r = u.request(request_id, lock=True)
            if r is None or player.id not in (r.sender, r.recipient):
                raise RequestNotFound(request_id)
            if (r.recipient if as_recipient else r.sender) != player.id:
                raise SelfAction("this request is for the other player to answer" if as_recipient
                                 else "only its sender can take a request back")
            if r.status is not RequestStatus.PENDING:
                raise RequestClosed(f"the request is {r.status.value} already")
            if status is RequestStatus.ACCEPTED:
                befriend(self.deps, u, out, r, now)
            else:
                r.status, r.updated_at = status, now
                u.save_request(r)
                out.add([r.sender, r.recipient], "friend_request", request_view(u, r))
            view = request_view(u, r)
        out.send(self.deps.hub)
        return view


class AcceptRequest(_Answer):
    def __call__(self, player: Player, request_id: str) -> RequestView:
        return self.answer(player, request_id, True, RequestStatus.ACCEPTED)


class DeclineRequest(_Answer):
    def __call__(self, player: Player, request_id: str) -> RequestView:
        return self.answer(player, request_id, True, RequestStatus.DECLINED)


class CancelRequest(_Answer):
    def __call__(self, player: Player, request_id: str) -> RequestView:
        return self.answer(player, request_id, False, RequestStatus.CANCELLED)


# ------------------------------------------------------------------ blocks


class ListBlocks(_UseCase):
    def __call__(self, player: Player) -> list[PlayerView]:
        with self.deps.store.unit() as u:
            me = ensure_player(self.deps, u, player, self.deps.clock.now())
            blocks = u.blocks_of(me.id)
            recs = u.players(b.blocked for b in blocks)
            return [PlayerView(id=b.blocked, name=recs[b.blocked].name if b.blocked in recs else None,
                               relation="blocked") for b in blocks]


class SetAvatar(_UseCase):
    """The player's profile picture (PNG, JPEG or WebP, checked from its bytes); their friends see it at once."""

    def __call__(self, player: Player, data: bytes) -> MeView:
        kind = check_avatar(data)
        return self.change(player, (kind, data))

    def change(self, player: Player, image: tuple[str, bytes] | None) -> MeView:
        now, out = self.deps.clock.now(), Outbox()
        with self.deps.store.unit() as u:
            rec = ensure_player(self.deps, u, player, now)
            if image is None:
                u.remove_avatar(rec.id)
                rec.avatar = 0
            else:
                u.save_avatar(rec.id, *image)
                rec.avatar = max(rec.avatar + 1, int(now.timestamp() * 1000))  # (a new version: no cached copy)
            u.save_player(rec)
            view = me_view(u, rec)
            out.add([rec.id], "me", view)
            for f in u.friends_of(rec.id):  # (each friend's view of the player, with the new picture)
                conversation = u.directs_of(f.friend).get(rec.id)
                out.add([f.friend], "friend", friend_view(self.deps, rec, f.since, conversation, now))
        out.send(self.deps.hub)
        return view


class RemoveAvatar(SetAvatar):
    def __call__(self, player: Player, data: bytes = b"") -> MeView:
        return self.change(player, None)


class GetAvatar(_UseCase):
    """A player's profile picture (public: images are loaded without a token)."""

    def __call__(self, player_id: str) -> AvatarImage:
        with self.deps.store.unit() as u:
            rec = u.player(player_id)
            image = u.avatar(player_id) if rec is not None and rec.avatar else None
            if rec is None or image is None:
                raise AvatarNotFound(player_id)
            return AvatarImage(content_type=image[0], data=image[1], version=rec.avatar)


class AvatarVersions(_UseCase):
    """Which of these players have a profile picture, and its version (public, as the pictures are): any page
    that names players shows theirs with one look-up. Unknown players have none; the first ``MAX_AVATAR_LOOKUP``
    ids are looked up."""

    def __call__(self, ids: Iterable[str]) -> dict[str, int | None]:
        wanted = list(dict.fromkeys(i for i in ids if i))[:MAX_AVATAR_LOOKUP]
        with self.deps.store.unit() as u:
            recs = u.players(wanted)
        return {i: (recs[i].avatar or None) if i in recs else None for i in wanted}


class BlockPlayer(_UseCase):
    """No friendship, no request, no direct message between the two any more (their old messages stay)."""

    def __call__(self, player: Player, other: str) -> PlayerView:
        now, out = self.deps.clock.now(), Outbox()
        with self.deps.store.unit() as u:
            me = ensure_player(self.deps, u, player, now)
            target = existing(u, other)
            if target.id == me.id:
                raise SelfAction("you can't block yourself")
            if u.block(me.id, target.id) is None:
                u.add_block(Block(blocker=me.id, blocked=target.id, at=now))
                unfriend(u, out, me.id, target.id)
                pending = u.pending_between(me.id, target.id, lock=True)
                if pending is not None:
                    pending.status = RequestStatus.CANCELLED if pending.sender == me.id else RequestStatus.DECLINED
                    pending.updated_at = now
                    u.save_request(pending)
                    out.add([me.id, target.id], "friend_request", request_view(u, pending))
            view = player_view(self.deps, u, me.id, target, now)
        out.send(self.deps.hub)
        return view


class UnblockPlayer(_UseCase):
    def __call__(self, player: Player, other: str) -> None:
        with self.deps.store.unit() as u:
            me = ensure_player(self.deps, u, player, self.deps.clock.now())
            u.remove_block(me.id, other)


# ------------------------------------------------------------------ conversations


class ListConversations(_UseCase):
    """The player's conversations, the last written to first."""

    def __call__(self, player: Player) -> list[ConversationView]:
        with self.deps.store.unit() as u:
            me = ensure_player(self.deps, u, player, self.deps.clock.now())
            mine = {m.conversation: m for m in u.memberships(me.id)}
            ids = list(mine)
            convs = u.conversations(ids)
            members = u.members(ids)
            lasts = u.last_messages(ids)
            unread = u.unread(me.id, list(mine.values()))
            friends = {f.friend for f in u.friends_of(me.id)}
            names = u.players({m.player for ms in members.values() for m in ms} | mentioned(lasts.values()))
            views = [conversation_view(convs[i], mine[i], members.get(i, []), lasts.get(i), unread.get(i, 0), friends,
                                       names) for i in ids if i in convs]
        views.sort(key=lambda v: (v.updated_at, v.id), reverse=True)
        return views


class GetConversation(_UseCase):
    def __call__(self, player: Player, conversation_id: str) -> ConversationView:
        with self.deps.store.unit() as u:
            ensure_player(self.deps, u, player, self.deps.clock.now())
            c, _ = member_of(u, conversation_id, player.id)
            return one_conversation(u, c, player.id)


class OpenDirect(_UseCase):
    """The conversation with a friend (made the first time)."""

    def __call__(self, player: Player, other: str) -> ConversationView:
        now, out = self.deps.clock.now(), Outbox()
        with self.deps.store.unit() as u:
            me = ensure_player(self.deps, u, player, now)
            if other == me.id:
                raise SelfAction("a conversation with yourself? Write it down instead")
            c = u.direct_between(me.id, other, lock=True)
            if c is None:
                if u.friendship(me.id, other) is None:
                    raise NotFriends("you can only write to your friends")
                c = Conversation(id=self.deps.ids.new_id(), kind=ConversationKind.DIRECT, created_at=now,
                                 pair=pair_key(me.id, other))
                u.add_conversation(c)
                for p in (me.id, other):
                    u.save_member(Member(conversation=c.id, player=p, joined_at=now))
                tell_conversation(out, u, c, [me.id])
            view = one_conversation(u, c, me.id)
        out.send(self.deps.hub)
        return view


class CreateGroup(_UseCase):
    def __call__(self, player: Player, group: NewGroup) -> ConversationView:
        title = clean_title(group.title)
        now, out = self.deps.clock.now(), Outbox()
        with self.deps.store.unit() as u:
            me = ensure_player(self.deps, u, player, now)
            others = [p for p in dict.fromkeys(group.members) if p != me.id]
            if not others:
                raise NotFriends("a group needs at least one of your friends")
            if len(others) + 1 > MAX_GROUP_MEMBERS:
                raise GroupFull(f"a group has at most {MAX_GROUP_MEMBERS} players")
            for p in others:
                if u.friendship(me.id, p) is None:
                    raise NotFriends(f"{p!r} isn't your friend")
            for p in [me.id, *others]:
                if u.count_groups(p) >= MAX_GROUPS:
                    who = "you are" if p == me.id else f"{p!r} is"
                    raise TooManyGroups(f"{who} in {MAX_GROUPS} groups already")
            c = Conversation(id=self.deps.ids.new_id(), kind=ConversationKind.GROUP, created_at=now, title=title,
                             owner=me.id)
            u.add_conversation(c)
            for p in [me.id, *others]:
                u.save_member(Member(conversation=c.id, player=p, joined_at=now))
            post_system(self.deps, u, c, now, SystemEvent.CREATED, me.id, others, title)
            tell_conversation(out, u, c, [me.id, *others])
            view = one_conversation(u, c, me.id)
        out.send(self.deps.hub)
        return view


class UpdateConversation(_UseCase):
    """A group's title (any of its players), or muting it (yours)."""

    def __call__(self, player: Player, conversation_id: str, changes: ConversationChanges) -> ConversationView:
        now, out = self.deps.clock.now(), Outbox()
        with self.deps.store.unit() as u:
            ensure_player(self.deps, u, player, now)
            c, m = member_of(u, conversation_id, player.id, lock=True)
            if changes.muted is not None and changes.muted != m.muted:
                m.muted = changes.muted
                u.save_member(m)
                tell_conversation(out, u, c, [player.id])
            if changes.title is not None:
                if c.kind is not ConversationKind.GROUP:
                    raise NotAGroup("only a group has a title")
                title = clean_title(changes.title)
                if title != c.title:
                    c.title = title
                    msg = post_system(self.deps, u, c, now, SystemEvent.RENAMED, player.id, title=title)
                    tell_message(out, u, c, msg)
                    tell_conversation(out, u, c, active_players(u, c))
            view = one_conversation(u, c, player.id)
        out.send(self.deps.hub)
        return view


class AddMembers(_UseCase):
    """Friends of the caller join a group (they read what is written from then on)."""

    def __call__(self, player: Player, conversation_id: str, players: Sequence[str]) -> ConversationView:
        now, out = self.deps.clock.now(), Outbox()
        with self.deps.store.unit() as u:
            ensure_player(self.deps, u, player, now)
            c, _ = member_of(u, conversation_id, player.id, lock=True)
            if c.kind is not ConversationKind.GROUP:
                raise NotAGroup("only a group takes new players")
            current = set(active_players(u, c))
            new = [p for p in dict.fromkeys(players) if p not in current]
            for p in new:
                if u.friendship(player.id, p) is None:
                    raise NotFriends(f"{p!r} isn't your friend")
            if len(current) + len(new) > MAX_GROUP_MEMBERS:
                raise GroupFull(f"a group has at most {MAX_GROUP_MEMBERS} players")
            for p in new:
                if u.count_groups(p) >= MAX_GROUPS:
                    raise TooManyGroups(f"{p!r} is in {MAX_GROUPS} groups already")
            if new:
                for p in new:
                    old = u.member(c.id, p)
                    joined = Member(conversation=c.id, player=p, joined_at=now, since_seq=c.last_seq,
                                    last_read=c.last_seq)
                    u.save_member(joined if old is None else replace(old, joined_at=now, since_seq=c.last_seq,
                                                                     last_read=c.last_seq, muted=False, left_at=None))
                msg = post_system(self.deps, u, c, now, SystemEvent.ADDED, player.id, new)
                tell_message(out, u, c, msg)
                tell_conversation(out, u, c, active_players(u, c))
            view = one_conversation(u, c, player.id)
        out.send(self.deps.hub)
        return view


class RemoveMember(_UseCase):
    """Leaving a group (``member`` is the caller), or its owner removing a player. A group whose owner leaves
    goes to the player who has been in it longest."""

    def __call__(self, player: Player, conversation_id: str, member: str) -> ConversationView | None:
        now, out = self.deps.clock.now(), Outbox()
        with self.deps.store.unit() as u:
            ensure_player(self.deps, u, player, now)
            c, _ = member_of(u, conversation_id, player.id, lock=True)
            if c.kind is not ConversationKind.GROUP:
                raise NotAGroup("a direct conversation can't be left")
            leaving = member == player.id
            if not leaving and c.owner != player.id:
                raise NotOwner("only the group's owner removes players")
            gone = u.member(c.id, member)
            if gone is None or not gone.active:
                raise PlayerNotFound(member)
            gone.left_at = now
            u.save_member(gone)
            rest = active_players(u, c)
            if c.owner == member:
                c.owner = rest[0] if rest else None
            msg = post_system(self.deps, u, c, now, SystemEvent.LEFT if leaving else SystemEvent.REMOVED, player.id,
                              [member])
            out.add([member], "conversation_left", Gone(id=c.id))
            tell_message(out, u, c, msg)
            tell_conversation(out, u, c, rest)
            view = None if leaving else one_conversation(u, c, player.id)
        out.send(self.deps.hub)
        return view


# ------------------------------------------------------------------ messages


class ListMessages(_UseCase):
    """Oldest first: the last ``limit`` before ``before`` (or the last ones), or the first ``limit`` after
    ``after``. A player who joined a group later reads it from then on."""

    def __call__(self, player: Player, conversation_id: str, before: int | None = None, after: int | None = None,
                 limit: int = 50) -> list[MessageView]:
        with self.deps.store.unit() as u:
            ensure_player(self.deps, u, player, self.deps.clock.now())
            c, m = member_of(u, conversation_id, player.id)
            msgs = u.messages(c.id, m.since_seq, before, after, max(1, min(limit, MAX_PAGE)))
            names = u.players(mentioned(msgs))
            return [message_view(x, names) for x in msgs]


class SendMessage(_UseCase):
    """A text, or one of the caller's runs (read from the game API with their token, as it is now), or a seed,
    each with an optional note."""

    def __call__(self, player: Player, conversation_id: str, message: NewMessage) -> MessageView:
        if message.run is not None and message.seed is not None:
            raise InvalidMessage("a message shares a run or a seed, not both")
        shares = message.run is not None or message.seed is not None
        text = clean_note(message.text) if shares else clean_text(message.text or "")
        seed = check_seed(message.seed.seed, message.seed.deck, message.seed.stake) if message.seed else None
        with self.deps.store.unit() as u:  # (a quick check before reading the game API)
            member_of(u, conversation_id, player.id)
        run = self.deps.runs.run(player, message.run) if message.run is not None else None
        now, out = self.deps.clock.now(), Outbox()
        with self.deps.store.unit() as u:
            me = ensure_player(self.deps, u, player, now)
            c, m = member_of(u, conversation_id, me.id, lock=True)
            if c.kind is ConversationKind.DIRECT:
                other = next((p for p in active_players(u, c) if p != me.id), None)
                if other is None or u.friendship(me.id, other) is None:
                    raise CantMessage("you can only write to your friends")
            if u.count_messages_since(me.id, now - MESSAGE_WINDOW) >= MESSAGE_BURST:
                raise SlowDown("that's a lot of messages: wait a few seconds")
            if run is not None:
                msg = post(self.deps, u, c, now, me.id, MessageKind.RUN, text, {"run": run.to_json()})
            elif seed is not None:
                msg = post(self.deps, u, c, now, me.id, MessageKind.SEED, text, {"seed": seed.to_json()})
            else:
                msg = post(self.deps, u, c, now, me.id, MessageKind.TEXT, text)
            m.last_read = msg.seq  # (one's own message is read)
            u.save_member(m)
            view = tell_message(out, u, c, msg)
        out.send(self.deps.hub)
        return view


class DeleteMessage(_UseCase):
    """Its sender takes a message back: it stays as "deleted", without its text."""

    def __call__(self, player: Player, conversation_id: str, message_id: str) -> MessageView:
        now, out = self.deps.clock.now(), Outbox()
        with self.deps.store.unit() as u:
            ensure_player(self.deps, u, player, now)
            c, m = member_of(u, conversation_id, player.id)
            msg = u.message(message_id)
            if msg is None or msg.conversation != c.id or msg.seq <= m.since_seq:
                raise MessageNotFound(message_id)
            if msg.sender != player.id:
                raise NotOwner("only its sender can delete a message")
            if msg.deleted_at is None:
                msg.deleted_at, msg.text, msg.attachment = now, "", None
                u.save_message(msg)
                view = tell_message(out, u, c, msg, "message_deleted")
            else:
                view = message_view(msg, u.players(mentioned([msg])))
        out.send(self.deps.hub)
        return view


class MarkRead(_UseCase):
    """The player has read the conversation up to message ``seq`` (the others see it: read receipts)."""

    def __call__(self, player: Player, conversation_id: str, seq: int) -> None:
        out = Outbox()
        with self.deps.store.unit() as u:
            ensure_player(self.deps, u, player, self.deps.clock.now())
            c, m = member_of(u, conversation_id, player.id)
            seq = min(seq, c.last_seq)
            if seq > m.last_read:
                m.last_read = seq
                u.save_member(m)
                out.add(active_players(u, c), "read", ReadView(conversation=c.id, player=player.id, seq=seq))
        out.send(self.deps.hub)


class Typing(_UseCase):
    """The player is writing: the others see it for a few seconds (nothing is kept)."""

    def __call__(self, player: Player, conversation_id: str) -> None:
        with self.deps.store.unit() as u:
            me = ensure_player(self.deps, u, player, self.deps.clock.now())
            c, _ = member_of(u, conversation_id, me.id)
            others = [p for p in active_players(u, c) if p != me.id]
            if c.kind is ConversationKind.DIRECT and not any(u.friendship(me.id, p) for p in others):
                return
        self.deps.hub.publish(others, Event("typing", TypingView(conversation=c.id,
                                                                 player=PlayerRef(id=me.id, name=me.name))))


# ------------------------------------------------------------------ the event stream and presence


class Subscribe(_UseCase):
    """A new event stream of the player's (on the event loop that reads it: nothing is read from the store)."""

    def __call__(self, player: Player) -> Subscription:
        return self.deps.hub.subscribe(player.id)


class StreamOpened(_UseCase):
    """The player is online (their friends are told); what the stream says first."""

    def __call__(self, player: Player) -> MeView:
        now, out = self.deps.clock.now(), Outbox()
        with self.deps.store.unit() as u:
            view = me_view(u, ensure_player(self.deps, u, player, now))
        if self.deps.presence.connect(player.id, now):  # (once the stream is sure to open)
            with self.deps.store.unit() as u:
                rec = existing(u, player.id)
                rec.last_seen = now
                u.save_player(rec)
                if rec.show_presence:
                    announce(out, self.deps, u, rec, now)
        out.send(self.deps.hub)
        return view


class StreamClosed(_UseCase):
    def __call__(self, player: Player) -> None:
        self.deps.presence.disconnect(player.id, self.deps.clock.now())


class SettlePresence(_UseCase):
    """Tells friends who has gone offline, or closed the game (every few seconds)."""

    def __call__(self) -> None:
        now = self.deps.clock.now()
        gone = self.deps.presence.settle(now)
        if not gone:
            return
        out = Outbox()
        with self.deps.store.unit() as u:
            for rec in u.players(gone).values():
                rec.last_seen = now
                u.save_player(rec)
                if rec.show_presence:
                    announce(out, self.deps, u, rec, now)
        out.send(self.deps.hub)


# ------------------------------------------------------------------ invites to a match


def invite_view(u: Unit, i: Invite) -> InviteView:
    names = u.players([i.sender, i.recipient])
    return InviteView(id=i.id, sender=ref(names, i.sender), recipient=ref(names, i.recipient), mode=i.mode,
                      code=i.code, status=i.status, created_at=i.created_at, expires_at=i.expires_at)


class SendInvite(_UseCase):
    """Invite a friend to the caller's match waiting for players (read from the game API with their token: the
    code is the API's, never the client's). Again to the same friend and match: the same invite, open longer."""

    def __call__(self, player: Player, invite: NewInvite) -> InviteView:
        if self.deps.matches is None:
            raise GameApiUnavailable("invites are off on this server")
        with self.deps.store.unit() as u:  # (a quick check before reading the game API)
            if invite.to == player.id:
                raise SelfAction("you are in your match already")
            if u.friendship(player.id, invite.to) is None:
                raise NotFriends("you can only invite your friends")
        match = self.deps.matches.open_match(player)
        now, out = self.deps.clock.now(), Outbox()
        with self.deps.store.unit() as u:
            me = ensure_player(self.deps, u, player, now)
            if u.friendship(me.id, invite.to) is None:
                raise NotFriends("you can only invite your friends")
            i = u.open_invite(me.id, invite.to, match.code, now, lock=True)
            if i is not None:
                i.expires_at, i.updated_at = now + INVITE_TTL, now
                u.save_invite(i)
            else:
                if u.count_invites_since(me.id, now - timedelta(hours=1)) >= INVITES_PER_HOUR:
                    raise SlowDown("that's a lot of invites: wait a little")
                i = Invite(id=self.deps.ids.new_id(), sender=me.id, recipient=invite.to, mode=match.mode,
                           code=match.code, match=match.id, status=InviteStatus.PENDING, created_at=now,
                           expires_at=now + INVITE_TTL, updated_at=now)
                u.add_invite(i)
            view = invite_view(u, i)
            out.add([me.id, invite.to], "invite", view)
        out.send(self.deps.hub)
        return view


class ListInvites(_UseCase):
    """The caller's open invites, newest first."""

    def __call__(self, player: Player) -> list[InviteView]:
        now = self.deps.clock.now()
        with self.deps.store.unit() as u:
            me = ensure_player(self.deps, u, player, now)
            return [invite_view(u, i) for i in u.invites_to(me.id, now)]


class AnswerInvite(_UseCase):
    """The recipient takes the invite (then joins the match with its code) or declines it."""

    def __call__(self, player: Player, invite_id: str, accept: bool) -> InviteView:
        now, out = self.deps.clock.now(), Outbox()
        with self.deps.store.unit() as u:
            ensure_player(self.deps, u, player, now)
            i = u.invite(invite_id, lock=True)
            if i is None or player.id not in (i.sender, i.recipient):
                raise InviteNotFound(invite_id)
            if i.recipient != player.id:
                raise SelfAction("this invite is for your friend to answer")
            if not i.open(now):
                raise InviteClosed("the invite is over: it was answered, or it expired")
            i.status, i.updated_at = (InviteStatus.ACCEPTED if accept else InviteStatus.DECLINED), now
            u.save_invite(i)
            view = invite_view(u, i)
            out.add([i.sender, i.recipient], "invite", view)
        out.send(self.deps.hub)
        return view


class GetInbox(_UseCase):
    """What waits for the player (a notification bell): friend requests to answer, unread conversations, invites."""

    def __call__(self, player: Player) -> InboxView:
        now = self.deps.clock.now()
        with self.deps.store.unit() as u:
            me = ensure_player(self.deps, u, player, now)
            requests = [request_view(u, r) for r in u.requests_of(me.id, "incoming")]
            invites = [invite_view(u, i) for i in u.invites_to(me.id, now)]
        conversations = [c for c in ListConversations(self.deps)(player) if c.unread > 0 and not c.muted]
        return InboxView(requests=requests, conversations=conversations, invites=invites,
                         count=len(requests) + len(conversations) + len(invites))


@dataclass(frozen=True)
class UseCases:
    authenticate: Authenticate
    me: GetMe
    update_me: UpdateMe
    new_code: NewFriendCode
    report_presence: ReportPresence
    find_players: FindPlayers
    player: GetPlayer
    player_by_code: PlayerByCode
    friends: ListFriends
    remove_friend: RemoveFriend
    requests: ListRequests
    send_request: SendRequest
    accept: AcceptRequest
    decline: DeclineRequest
    cancel: CancelRequest
    blocks: ListBlocks
    set_avatar: SetAvatar
    remove_avatar: RemoveAvatar
    avatar: GetAvatar
    avatar_versions: AvatarVersions
    block: BlockPlayer
    unblock: UnblockPlayer
    conversations: ListConversations
    conversation: GetConversation
    open_direct: OpenDirect
    create_group: CreateGroup
    update_conversation: UpdateConversation
    add_members: AddMembers
    remove_member: RemoveMember
    messages: ListMessages
    send: SendMessage
    delete_message: DeleteMessage
    mark_read: MarkRead
    typing: Typing
    subscribe: Subscribe
    stream_opened: StreamOpened
    stream_closed: StreamClosed
    settle_presence: SettlePresence
    send_invite: SendInvite
    invites: ListInvites
    answer_invite: AnswerInvite
    inbox: GetInbox


def build(deps: Deps, authenticator: Authenticator) -> UseCases:
    return UseCases(
        authenticate=Authenticate(authenticator), me=GetMe(deps), update_me=UpdateMe(deps),
        new_code=NewFriendCode(deps), report_presence=ReportPresence(deps), find_players=FindPlayers(deps),
        player=GetPlayer(deps), player_by_code=PlayerByCode(deps), friends=ListFriends(deps),
        remove_friend=RemoveFriend(deps), requests=ListRequests(deps), send_request=SendRequest(deps),
        accept=AcceptRequest(deps), decline=DeclineRequest(deps), cancel=CancelRequest(deps), blocks=ListBlocks(deps),
        set_avatar=SetAvatar(deps), remove_avatar=RemoveAvatar(deps), avatar=GetAvatar(deps),
        avatar_versions=AvatarVersions(deps), block=BlockPlayer(deps), unblock=UnblockPlayer(deps),
        conversations=ListConversations(deps),
        conversation=GetConversation(deps), open_direct=OpenDirect(deps), create_group=CreateGroup(deps),
        update_conversation=UpdateConversation(deps), add_members=AddMembers(deps), remove_member=RemoveMember(deps),
        messages=ListMessages(deps), send=SendMessage(deps), delete_message=DeleteMessage(deps),
        mark_read=MarkRead(deps), typing=Typing(deps), subscribe=Subscribe(deps), stream_opened=StreamOpened(deps),
        stream_closed=StreamClosed(deps), settle_presence=SettlePresence(deps), send_invite=SendInvite(deps),
        invites=ListInvites(deps), answer_invite=AnswerInvite(deps), inbox=GetInbox(deps))
