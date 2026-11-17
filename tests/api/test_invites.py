"""Invites to a match, and the inbox (what a notification bell shows)."""

from __future__ import annotations

from typing import Any

from balatro_social.domain import MatchCard
from tests.conftest import World


def lobby(world: World, who: str, code: str = "9H7W9V", mode: str = "pvp") -> None:
    world.runs.matches[who.lower()] = MatchCard(id=f"m-{who.lower()}", code=code, mode=mode)


def events(world: World, to: str, kind: str) -> list[Any]:
    return [e.data for players, e in world.hub.published if e.type == kind and to in players]


def test_an_invite_to_a_friend(world: World) -> None:
    world.friends("Ann", "Bob")
    lobby(world, "Ann")
    inv = world.call("POST", "/v1/invites", "Ann", {"to": "bob"}, status=201)
    assert (inv["mode"], inv["code"], inv["status"]) == ("pvp", "9H7W9V", "pending")
    assert inv["sender"]["name"] == "Ann" and inv["recipient"]["id"] == "bob"
    assert [e.id for e in events(world, "bob", "invite")] == [inv["id"]]
    assert [i["id"] for i in world.call("GET", "/v1/invites", "Bob")] == [inv["id"]]
    assert world.call("GET", "/v1/invites", "Ann") == []
    # again: the same invite, open longer
    world.clock.advance(minutes=5)
    again = world.call("POST", "/v1/invites", "Ann", {"to": "bob"}, status=201)
    assert again["id"] == inv["id"] and again["expires_at"] > inv["expires_at"]
    # only the recipient answers it
    world.call("POST", f"/v1/invites/{inv['id']}/accept", "Ann", status=422)
    world.call("POST", f"/v1/invites/{inv['id']}/accept", "Cy", status=404)
    taken = world.call("POST", f"/v1/invites/{inv['id']}/accept", "Bob")
    assert taken["status"] == "accepted" and events(world, "ann", "invite")[-1].status == "accepted"
    assert world.call("GET", "/v1/invites", "Bob") == []
    assert world.call("POST", f"/v1/invites/{inv['id']}/decline", "Bob", status=409)["code"] == "invite_closed"


def test_invites_go_to_friends_with_a_match_open(world: World) -> None:
    for who in ("Ann", "Cy"):
        world.call("GET", "/v1/me", who)
    lobby(world, "Ann")
    assert world.call("POST", "/v1/invites", "Ann", {"to": "cy"}, status=403)["code"] == "not_friends"
    world.friends("Ann", "Cy")
    del world.runs.matches["ann"]
    assert world.call("POST", "/v1/invites", "Ann", {"to": "cy"}, status=409)["code"] == "no_open_match"
    world.runs.down = True
    assert world.call("POST", "/v1/invites", "Ann", {"to": "cy"}, status=503)["code"] == "game_api_unavailable"
    world.call("POST", "/v1/invites", "Ann", {"to": "ann"}, status=422)


def test_invites_expire(world: World) -> None:
    world.friends("Ann", "Bob")
    lobby(world, "Ann")
    inv = world.call("POST", "/v1/invites", "Ann", {"to": "bob"}, status=201)
    world.clock.advance(minutes=11)
    assert world.call("GET", "/v1/invites", "Bob") == []
    world.call("POST", f"/v1/invites/{inv['id']}/accept", "Bob", status=409)


def test_the_inbox(world: World) -> None:
    world.friends("Ann", "Bob")
    for who in ("Cy",):
        world.call("GET", "/v1/me", who)
    assert world.call("GET", "/v1/inbox", "Bob") == {"requests": [], "conversations": [], "invites": [], "count": 0}
    world.call("POST", "/v1/friends/requests", "Cy", {"to": "bob"})
    direct = world.call("POST", "/v1/conversations/direct", "Ann", {"player": "bob"})
    world.call("POST", f"/v1/conversations/{direct['id']}/messages", "Ann", {"text": "gg"})
    lobby(world, "Ann")
    world.call("POST", "/v1/invites", "Ann", {"to": "bob"})
    box = world.call("GET", "/v1/inbox", "Bob")
    assert box["count"] == 3 and len(box["requests"]) == 1 and box["requests"][0]["sender"]["name"] == "Cy"
    assert [c["id"] for c in box["conversations"]] == [direct["id"]] and box["conversations"][0]["unread"] == 1
    assert box["invites"][0]["code"] == "9H7W9V"
    # (the sender's own message isn't unread for them)
    assert world.call("GET", "/v1/inbox", "Ann")["count"] == 0
