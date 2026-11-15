"""The same scenarios on both stores (memory, and PostgreSQL when BALATRO_SOCIAL_TEST_DATABASE_URL is set)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from balatro_social.application.dto import ConversationChanges, NewGroup, NewMessage, NewRequest, SeedInput
from balatro_social.domain import (
    Conversation,
    ConversationKind,
    FriendRequest,
    Member,
    Message,
    MessageKind,
    PlayerRecord,
    RequestStatus,
)
from balatro_social.infrastructure.persistence import MemoryStore, PostgresStore
from tests.conftest import World, make_world
from tests.fakes import T0


@pytest.fixture(params=["memory", "postgres"])
def store_world(request: pytest.FixtureRequest) -> World:
    if request.param == "memory":
        return make_world(MemoryStore())
    make: Callable[[], PostgresStore] = request.getfixturevalue("pg")
    return make_world(make())


def test_friends_chat_and_groups(store_world: World) -> None:
    w = store_world
    ann, bob, cy = w.p("Ann"), w.p("Bob"), w.p("Cy")
    for p in (ann, bob, cy):
        w.uses.me(p)
    req = w.uses.send_request(ann, NewRequest(to="bob"))
    assert [r.id for r in w.uses.requests(bob, "incoming")] == [req.id]
    assert w.uses.send_request(bob, NewRequest(to="ann")).status is RequestStatus.ACCEPTED
    code = w.uses.me(cy).friend_code
    w.uses.accept(cy, w.uses.send_request(ann, NewRequest(code=code)).id)
    assert sorted(f.id for f in w.uses.friends(ann)) == ["bob", "cy"]
    assert w.uses.me(ann).friends == 2

    d = w.uses.open_direct(ann, "bob")
    assert w.uses.open_direct(bob, "ann").id == d.id
    for i in range(5):
        w.uses.send(ann if i % 2 == 0 else bob, d.id, NewMessage(text=f"m{i}"))
    w.runs.add("ann", "r1")
    w.uses.send(ann, d.id, NewMessage(run="r1", text="gg"))
    w.uses.send(bob, d.id, NewMessage(seed=SeedInput(seed="abc", deck="b_red", stake=1)))
    msgs = w.uses.messages(ann, d.id)
    assert [m.seq for m in msgs] == list(range(1, 8))
    assert msgs[5].run is not None and msgs[5].run.played_at == T0 and msgs[6].seed is not None
    assert [m.seq for m in w.uses.messages(ann, d.id, before=4, limit=2)] == [2, 3]
    assert [m.seq for m in w.uses.messages(ann, d.id, after=5)] == [6, 7]
    assert w.uses.me(ann).unread == 1
    w.uses.mark_read(ann, d.id, 7)
    assert w.uses.me(ann).unread == 0
    deleted = w.uses.delete_message(bob, d.id, msgs[6].id)
    assert deleted.deleted and w.uses.messages(ann, d.id)[-1].deleted

    g = w.uses.create_group(ann, NewGroup(title="Jimbos", members=("bob",)))
    w.uses.send(bob, g.id, NewMessage(text="secret"))
    w.uses.add_members(ann, g.id, ["cy"])
    assert [m.kind for m in w.uses.messages(cy, g.id)] == [MessageKind.SYSTEM]  # (from when Cy joined)
    w.uses.update_conversation(cy, g.id, ConversationChanges(title="Club", muted=True))
    views = {c.id: c for c in w.uses.conversations(cy)}
    assert views[g.id].title == "Club" and views[g.id].muted
    w.uses.remove_member(ann, g.id, "ann")
    assert w.uses.conversation(bob, g.id).owner == "bob"
    assert [c.id for c in w.uses.conversations(ann)] == [d.id]

    w.uses.block(ann, "bob")
    assert [f.id for f in w.uses.friends(ann)] == ["cy"]
    assert w.uses.conversation(bob, d.id).can_send is False
    assert w.uses.find_players(bob, "an") == []
    w.uses.unblock(ann, "bob")
    assert [p.id for p in w.uses.find_players(bob, "an")] == ["ann"]


def test_the_stores_queries(store_world: World) -> None:
    store = w_store(store_world)
    with store.unit() as u:
        for pid, name in (("a", "Ann"), ("b", "Anna_%"), ("c", "Bob")):
            assert u.add_player(PlayerRecord(id=pid, name=name, code=f"CODE{pid.upper()}AAA"[:8], created_at=T0))
        assert not u.add_player(PlayerRecord(id="a", name="Twice", code="ZZZZZZZZ", created_at=T0))
        assert [p.id for p in u.find_players("anna_%", 10)] == ["b"]
        assert [p.id for p in u.find_players("an", 10)] == ["a", "b"]
        assert u.player_by_code("CODEBAAA") is not None
        u.add_request(FriendRequest(id="r1", sender="a", recipient="b", status=RequestStatus.PENDING,
                                    created_at=T0, updated_at=T0))
        found = u.pending_between("b", "a", lock=True)
        assert found is not None and found.id == "r1"
        u.add_conversation(Conversation(id="c1", kind=ConversationKind.GROUP, created_at=T0, title="t", owner="a"))
        for p in ("a", "b"):
            u.save_member(Member(conversation="c1", player=p, joined_at=T0))
        for seq in (1, 2, 3):
            u.add_message(Message(id=f"m{seq}", conversation="c1", seq=seq, sender="a" if seq < 3 else "b",
                                  kind=MessageKind.TEXT, text=str(seq), created_at=T0))
        conv = u.conversation("c1", lock=True)
        assert conv is not None
        conv.last_seq = 3
        u.save_conversation(conv)
        mine = u.memberships("a")
        assert u.unread("a", mine) == {"c1": 1} and u.unread("b", u.memberships("b")) == {"c1": 2}
        assert u.last_messages(["c1"])["c1"].id == "m3"
        assert u.count_groups("a") == 1 and u.count_messages_since("a", T0.replace(year=2025)) == 2
    with pytest.raises(RuntimeError):  # (a unit that fails changes nothing)
        with store.unit() as u:
            u.remove_friendship("a", "b")
            u.add_friendship("a", "c", T0)
            raise RuntimeError("boom")
    with store.unit() as u:
        assert u.friends_of("a") == []


def w_store(w: World) -> MemoryStore | PostgresStore:
    store = w.uses.me.deps.store
    assert isinstance(store, MemoryStore | PostgresStore)
    return store


def test_migrations_run_once(pg: Callable[[], PostgresStore]) -> None:
    first = pg()
    with first.unit() as u:
        u.add_player(PlayerRecord(id="a", name="Ann", code="AAAAAAAA", created_at=T0))
    second = pg()  # (the same schema: nothing is applied again)
    with second.unit() as u:
        assert u.player("a") is not None


def test_pictures_are_kept(store_world: World) -> None:
    from tests.unit.test_images import png
    w = store_world
    ann = w.p("Ann")
    first = w.uses.set_avatar(ann, png(8, 8))
    image = w.uses.avatar("ann")
    assert image.data == png(8, 8) and image.content_type == "image/png" and image.version == first.avatar
    w.uses.set_avatar(ann, png(4, 4))
    assert w.uses.avatar("ann").data == png(4, 4)
    w.uses.remove_avatar(ann)
    with pytest.raises(Exception, match="no profile picture"):
        w.uses.avatar("ann")
