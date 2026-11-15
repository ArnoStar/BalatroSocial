"""Conversations over HTTP: direct messages, groups, sharing runs and seeds, unread counts, limits."""

from __future__ import annotations

from typing import Any

from balatro_social.domain import MAX_GROUP_MEMBERS, MESSAGE_BURST
from tests.conftest import World


def direct(world: World, a: str = "Ann", b: str = "Bob") -> dict[str, Any]:
    world.friends(a, b)
    conv: dict[str, Any] = world.call("POST", "/v1/conversations/direct", a, {"player": b.lower()})
    return conv


def say(world: World, who: str, conv: str, text: str, status: int = 201) -> Any:
    return world.call("POST", f"/v1/conversations/{conv}/messages", who, {"text": text}, status=status)


def test_friends_write_to_each_other(world: World) -> None:
    world.call("GET", "/v1/me", "Cy")
    conv = direct(world)
    assert conv["kind"] == "direct" and conv["can_send"] and conv["last_message"] is None
    assert [m["id"] for m in conv["members"]] == ["ann", "bob"]
    # the same conversation for both, made once
    assert world.call("POST", "/v1/conversations/direct", "Bob", {"player": "ann"})["id"] == conv["id"]
    assert world.call("GET", "/v1/friends", "Ann")[0]["conversation"] == conv["id"]
    assert world.call("POST", "/v1/conversations/direct", "Ann", {"player": "cy"}, status=403)["code"] == \
        "not_friends"
    assert world.call("GET", f"/v1/conversations/{conv['id']}", "Cy", status=404)["code"] == "conversation_not_found"

    world.hub.clear()
    m = say(world, "Ann", conv["id"], "  gg  ")
    assert (m["seq"], m["text"], m["kind"], m["sender"]["name"]) == (1, "gg", "text", "Ann")
    assert [e.data.id for e in world.hub.to("bob", "message")] == [m["id"]]
    assert [e.data.id for e in world.hub.to("ann", "message")] == [m["id"]]  # (her other tabs)
    say(world, "Bob", conv["id"], "wp")
    say(world, "Ann", conv["id"], "again?")
    bob = world.call("GET", "/v1/conversations", "Bob")[0]
    # (writing, Bob read everything before his message: Ann's last one waits)
    assert bob["unread"] == 1 and bob["last_message"]["text"] == "again?" and bob["last_seq"] == 3
    assert world.call("GET", "/v1/me", "Bob")["unread"] == 1
    assert world.call("GET", "/v1/conversations", "Ann")[0]["unread"] == 0  # (one's own messages are read)
    assert [x["text"] for x in world.call("GET", f"/v1/conversations/{conv['id']}/messages", "Bob")] == \
        ["gg", "wp", "again?"]

    world.hub.clear()
    world.call("POST", f"/v1/conversations/{conv['id']}/read", "Bob", {"seq": 99}, status=204)
    assert world.call("GET", "/v1/me", "Bob")["unread"] == 0
    assert world.hub.to("ann", "read")[0].data.seq == 3  # (read receipts: as far as there are messages)
    members = {m["id"]: m["last_read"] for m in world.call("GET", f"/v1/conversations/{conv['id']}", "Ann")["members"]}
    assert members == {"ann": 3, "bob": 3}
    world.call("POST", f"/v1/conversations/{conv['id']}/typing", "Bob", status=204)
    assert [e.data.player.name for e in world.hub.to("ann", "typing")] == ["Bob"] and not world.hub.to("bob", "typing")


def test_messages_are_checked_and_limited(world: World) -> None:
    conv = direct(world)["id"]
    assert say(world, "Ann", conv, "  \n ", status=422)["code"] == "invalid_message"
    assert say(world, "Ann", conv, "x" * 2001, status=422)["code"] == "invalid_message"
    assert say(world, "Ann", conv, "a\x00b")["text"] == "ab"
    for _ in range(MESSAGE_BURST - 1):
        say(world, "Ann", conv, "spam")
    assert say(world, "Ann", conv, "too much", status=429)["code"] == "slow_down"
    say(world, "Bob", conv, "(Bob isn't limited by Ann's messages)")
    world.clock.advance(seconds=31)
    say(world, "Ann", conv, "ok now")


def test_messages_come_in_pages(world: World) -> None:
    conv = direct(world)["id"]
    for i in range(1, 46):
        say(world, "Ann", conv, f"m{i}")
        if i % MESSAGE_BURST == 0:
            world.clock.advance(seconds=31)
    page = world.call("GET", f"/v1/conversations/{conv}/messages?limit=20", "Bob")
    assert [m["seq"] for m in page] == list(range(26, 46))
    older = world.call("GET", f"/v1/conversations/{conv}/messages?limit=20&before=26", "Bob")
    assert [m["seq"] for m in older] == list(range(6, 26))
    newer = world.call("GET", f"/v1/conversations/{conv}/messages?after=40", "Bob")
    assert [m["seq"] for m in newer] == [41, 42, 43, 44, 45]


def test_only_the_sender_deletes_a_message(world: World) -> None:
    conv = direct(world)["id"]
    m = say(world, "Ann", conv, "oops")
    assert world.call("DELETE", f"/v1/conversations/{conv}/messages/{m['id']}", "Bob", status=403)["code"] == \
        "not_owner"
    world.hub.clear()
    gone = world.call("DELETE", f"/v1/conversations/{conv}/messages/{m['id']}", "Ann")
    assert gone["deleted"] and gone["text"] == ""
    assert world.hub.to("bob", "message_deleted")[0].data.id == m["id"]
    assert world.call("GET", f"/v1/conversations/{conv}/messages", "Bob")[0]["deleted"]
    assert world.call("GET", "/v1/me", "Bob")["unread"] == 0  # (a deleted message isn't waiting any more)
    assert world.call("DELETE", f"/v1/conversations/{conv}/messages/nope", "Ann", status=404)["code"] == \
        "message_not_found"


def test_sharing_runs_and_seeds(world: World) -> None:
    conv = direct(world)["id"]
    world.runs.add("ann", "run1", deck="b_plasma", stake=8, best_hand=9.9e9)
    m = world.call("POST", f"/v1/conversations/{conv}/messages", "Ann", {"run": "run1", "text": "look"}, status=201)
    run = m["run"]
    assert m["kind"] == "run" and m["text"] == "look"
    assert (run["id"], run["deck"], run["stake"], run["won"], run["best_hand"]) == ("run1", "b_plasma", 8, True, 9.9e9)
    assert world.call("GET", f"/v1/conversations/{conv}/messages", "Bob")[0]["run"]["seed"] == "ABCD1234"
    # only one's own runs (the game API is read with the sharer's token)
    r = world.call("POST", f"/v1/conversations/{conv}/messages", "Bob", {"run": "run1"}, status=404)
    assert r["code"] == "run_not_found"
    world.runs.down = True
    r = world.call("POST", f"/v1/conversations/{conv}/messages", "Ann", {"run": "run1"}, status=503)
    assert r["code"] == "game_api_unavailable"

    seed = world.call("POST", f"/v1/conversations/{conv}/messages", "Bob",
                      {"seed": {"seed": "jimbo123", "deck": "b_red", "stake": 2}}, status=201)
    assert seed["kind"] == "seed" and seed["seed"] == {"seed": "JIMBO123", "deck": "b_red", "stake": 2}
    assert seed["text"] == ""
    bad = world.call("POST", f"/v1/conversations/{conv}/messages", "Bob",
                     {"seed": {"seed": "no way!", "deck": "b_red", "stake": 2}}, status=422)
    assert bad["code"] == "invalid_seed"
    both = world.call("POST", f"/v1/conversations/{conv}/messages", "Ann",
                      {"run": "run1", "seed": {"seed": "X", "deck": "b_red", "stake": 1}}, status=422)
    assert both["code"] == "invalid_message"


def test_former_friends_read_but_dont_write(world: World) -> None:
    conv = direct(world)["id"]
    say(world, "Ann", conv, "bye")
    world.call("DELETE", "/v1/friends/bob", "Ann", status=204)
    view = world.call("GET", f"/v1/conversations/{conv}", "Bob")
    assert view["can_send"] is False and view["last_message"]["text"] == "bye"
    assert say(world, "Bob", conv, "wait", status=403)["code"] == "cant_message"
    world.hub.clear()
    world.call("POST", f"/v1/conversations/{conv}/typing", "Bob", status=204)
    assert not world.hub.to("ann", "typing")
    # friends again: the same conversation
    req = world.call("POST", "/v1/friends/requests", "Bob", {"to": "ann"})
    world.call("POST", f"/v1/friends/requests/{req['id']}/accept", "Ann")
    assert world.call("POST", "/v1/conversations/direct", "Bob", {"player": "ann"})["id"] == conv
    assert say(world, "Bob", conv, "hi again")["seq"] == 2


def test_groups(world: World) -> None:
    world.friends("Ann", "Bob")
    world.friends("Ann", "Cy")
    world.call("GET", "/v1/me", "Dee")
    r = world.call("POST", "/v1/conversations", "Ann", {"title": "x", "members": ["dee"]}, status=403)
    assert r["code"] == "not_friends"
    g = world.call("POST", "/v1/conversations", "Ann", {"title": " The  Jimbos ", "members": ["bob"]}, status=201)
    assert (g["kind"], g["title"], g["owner"]) == ("group", "The Jimbos", "ann")
    created = g["last_message"]
    assert created["kind"] == "system" and created["system"]["event"] == "created"
    assert created["system"]["by"]["name"] == "Ann" and [p["name"] for p in created["system"]["players"]] == ["Bob"]
    gid = g["id"]
    say(world, "Bob", gid, "before Cy")
    assert world.call("GET", "/v1/me", "Ann")["unread"] == 1

    # Bob adds a friend of his? Only his friends: Cy isn't
    r = world.call("POST", f"/v1/conversations/{gid}/members", "Bob", {"players": ["cy"]}, status=403)
    assert r["code"] == "not_friends"
    view = world.call("POST", f"/v1/conversations/{gid}/members", "Ann", {"players": ["cy"]})
    assert [m["name"] for m in view["members"]] == ["Ann", "Bob", "Cy"]
    texts = [m.get("text") or m["system"]["event"] for m in
             world.call("GET", f"/v1/conversations/{gid}/messages", "Cy")]
    assert texts == ["added"]  # (Cy reads from when they joined)
    assert world.call("GET", "/v1/me", "Cy")["unread"] == 0

    renamed = world.call("PATCH", f"/v1/conversations/{gid}", "Cy", {"title": "Jimbo Club"})
    assert renamed["title"] == "Jimbo Club" and renamed["last_message"]["system"]["event"] == "renamed"
    r = world.call("DELETE", f"/v1/conversations/{gid}/members/ann", "Bob", status=403)
    assert r["code"] == "not_owner"
    world.hub.clear()
    after = world.call("DELETE", f"/v1/conversations/{gid}/members/cy", "Ann")
    assert [m["id"] for m in after["members"]] == ["ann", "bob"]
    assert world.hub.to("cy", "conversation_left")[0].data.id == gid
    assert world.call("GET", f"/v1/conversations/{gid}", "Cy", status=404)["code"] == "conversation_not_found"
    assert [c["id"] for c in world.call("GET", "/v1/conversations", "Cy")] == []

    # the owner leaves: Bob owns it
    world.call("DELETE", f"/v1/conversations/{gid}/members/ann", "Ann", status=204)
    view = world.call("GET", f"/v1/conversations/{gid}", "Bob")
    assert view["owner"] == "bob" and [m["id"] for m in view["members"]] == ["bob"]
    assert view["last_message"]["system"]["event"] == "left"
    r = world.call("DELETE", f"/v1/conversations/{gid}/members/bob", "Ann", status=404)
    assert r["code"] == "conversation_not_found"

    r = world.call("PATCH", f"/v1/conversations/{direct(world, 'Bob', 'Cy')['id']}", "Bob", {"title": "x"},
                   status=409)
    assert r["code"] == "not_a_group"


def test_a_group_is_limited_and_can_be_muted(world: World) -> None:
    names = [f"F{i}" for i in range(MAX_GROUP_MEMBERS)]
    for n in names:
        world.friends("Ann", n)
    r = world.call("POST", "/v1/conversations", "Ann", {"title": "big", "members": [n.lower() for n in names]},
                   status=409)
    assert r["code"] == "group_full"
    g = world.call("POST", "/v1/conversations", "Ann", {"title": "big", "members": [n.lower() for n in names[:-1]]},
                   status=201)
    r = world.call("POST", f"/v1/conversations/{g['id']}/members", "Ann", {"players": [names[-1].lower()]},
                   status=409)
    assert r["code"] == "group_full"
    say(world, "F0", g["id"], "hi all")
    assert world.call("GET", "/v1/me", "F1")["unread"] == 1
    muted = world.call("PATCH", f"/v1/conversations/{g['id']}", "F1", {"muted": True})
    assert muted["muted"] and muted["unread"] == 1
    assert world.call("GET", "/v1/me", "F1")["unread"] == 0  # (a muted conversation doesn't count)
