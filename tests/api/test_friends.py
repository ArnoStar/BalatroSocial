"""Friends over HTTP: requests (by id, by code, crossing), answers, blocks, limits."""

from __future__ import annotations

from balatro_social.domain import MAX_PENDING_SENT, REQUESTS_PER_DAY
from tests.conftest import World


def test_sign_in_is_needed_but_for_health(world: World) -> None:
    c = world.client
    assert c.get("/health").json()["auth"] == "required"
    for path in ("/v1/me", "/v1/friends", "/v1/conversations", "/v1/events"):
        r = c.get(path)
        assert r.status_code == 401 and r.json()["code"] == "unauthenticated", path
    assert c.get("/v1/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_a_new_player_has_a_friend_code(world: World) -> None:
    me = world.call("GET", "/v1/me", "Ann")
    assert me["id"] == "ann" and me["name"] == "Ann" and me["friend_code"] == "AAAA-2222"
    assert (me["friends"], me["incoming"], me["unread"]) == (0, 0, 0)
    assert me["requests"] == "everyone" and me["show_presence"] is True
    # (the next code drawn is taken: another is drawn)
    assert world.call("GET", "/v1/me", "Bob")["friend_code"] == "AAAA-2223"
    new = world.call("POST", "/v1/me/code", "Ann")["friend_code"]
    assert new not in ("AAAA-2222", "AAAA-2223")
    assert world.call("GET", "/v1/codes/AAAA-2222", "Bob", status=404)["code"] == "code_not_found"
    assert world.call("GET", f"/v1/codes/{new.lower()}", "Bob")["id"] == "ann"


def test_a_request_accepted_makes_two_friends(world: World) -> None:
    world.call("GET", "/v1/me", "Ann")
    world.call("GET", "/v1/me", "Bob")
    req = world.call("POST", "/v1/friends/requests", "Ann", {"to": "bob"}, status=201)
    assert req["status"] == "pending" and req["sender"] == {"id": "ann", "name": "Ann", "avatar": None}
    assert [r["id"] for r in world.call("GET", "/v1/friends/requests?box=incoming", "Bob")] == [req["id"]]
    assert world.call("GET", "/v1/friends/requests?box=incoming", "Ann") == []
    assert world.call("GET", "/v1/me", "Bob")["incoming"] == 1
    assert world.call("GET", "/v1/players/bob", "Ann")["relation"] == "outgoing"
    assert world.call("GET", "/v1/players/ann", "Bob")["relation"] == "incoming"
    # (asking again changes nothing)
    assert world.call("POST", "/v1/friends/requests", "Ann", {"to": "bob"}, status=201)["id"] == req["id"]
    assert [e.type for e in world.hub.to("bob")] == ["friend_request"]

    world.hub.clear()
    done = world.call("POST", f"/v1/friends/requests/{req['id']}/accept", "Bob")
    assert done["status"] == "accepted"
    assert [f["id"] for f in world.call("GET", "/v1/friends", "Ann")] == ["bob"]
    friend = world.call("GET", "/v1/friends", "Bob")[0]
    assert friend["id"] == "ann" and friend["relation"] == "friend" and friend["since"]
    assert friend["presence"] == {"online": False, "activity": None, "last_seen": None}
    assert sorted(e.type for e in world.hub.to("ann")) == ["friend", "friend_request"]
    assert world.hub.to("ann", "friend")[0].data.id == "bob"
    assert world.call("GET", "/v1/me", "Bob")["incoming"] == 0
    assert world.call("POST", f"/v1/friends/requests/{req['id']}/decline", "Bob", status=409)["code"] == \
        "request_closed"
    assert world.call("POST", "/v1/friends/requests", "Ann", {"to": "bob"}, status=409)["code"] == "already_friends"

    world.call("DELETE", "/v1/friends/bob", "Ann", status=204)
    assert world.call("GET", "/v1/friends", "Bob") == []
    assert world.hub.to("bob", "friend_removed")[0].data.id == "ann"
    assert world.call("DELETE", "/v1/friends/bob", "Ann", status=403)["code"] == "not_friends"


def test_two_requests_crossing_make_friends_at_once(world: World) -> None:
    world.call("GET", "/v1/me", "Ann")
    world.call("GET", "/v1/me", "Bob")
    world.call("POST", "/v1/friends/requests", "Ann", {"to": "bob"})
    crossing = world.call("POST", "/v1/friends/requests", "Bob", {"to": "ann"}, status=201)
    assert crossing["status"] == "accepted" and crossing["sender"]["id"] == "ann"
    assert [f["id"] for f in world.call("GET", "/v1/friends", "Bob")] == ["ann"]


def test_requests_can_be_declined_or_taken_back(world: World) -> None:
    for who in ("Ann", "Bob", "Cy"):
        world.call("GET", "/v1/me", who)
    a = world.call("POST", "/v1/friends/requests", "Ann", {"to": "bob"})
    assert world.call("POST", f"/v1/friends/requests/{a['id']}/accept", "Ann", status=422)["code"] == "self"
    assert world.call("POST", f"/v1/friends/requests/{a['id']}/cancel", "Bob", status=422)["code"] == "self"
    assert world.call("POST", f"/v1/friends/requests/{a['id']}/accept", "Cy", status=404)["code"] == \
        "request_not_found"
    assert world.call("POST", f"/v1/friends/requests/{a['id']}/decline", "Bob")["status"] == "declined"
    b = world.call("POST", "/v1/friends/requests", "Ann", {"to": "cy"})
    assert world.call("POST", f"/v1/friends/requests/{b['id']}/cancel", "Ann")["status"] == "cancelled"
    assert world.call("GET", "/v1/friends/requests", "Ann") == []
    # a declined player may ask again
    assert world.call("POST", "/v1/friends/requests", "Ann", {"to": "bob"})["status"] == "pending"


def test_who_can_be_asked(world: World) -> None:
    world.call("GET", "/v1/me", "Ann")
    assert world.call("POST", "/v1/friends/requests", "Ann", {"to": "ann"}, status=422)["code"] == "self"
    assert world.call("POST", "/v1/friends/requests", "Ann", {"to": "nobody"}, status=404)["code"] == \
        "player_not_found"
    assert world.call("POST", "/v1/friends/requests", "Ann", {"code": "ZZZZ-ZZZZ"}, status=404)["code"] == \
        "code_not_found"
    assert world.call("POST", "/v1/friends/requests", "Ann", {}, status=422)["code"] == "invalid_request"
    assert world.call("POST", "/v1/friends/requests", "Ann", {"to": "x", "code": "y"}, status=422)["code"] == \
        "invalid_request"
    # a player who takes requests only with their code
    bob = world.call("PATCH", "/v1/me", "Bob", {"requests": "code"})
    assert bob["requests"] == "code"
    assert world.call("POST", "/v1/friends/requests", "Ann", {"to": "bob"}, status=403)["code"] == "cant_add"
    assert world.call("GET", "/v1/players?q=bo", "Ann") == []  # (not listed)
    req = world.call("POST", "/v1/friends/requests", "Ann", {"code": bob["friend_code"]}, status=201)
    assert req["recipient"]["id"] == "bob"


def test_finding_players_by_name(world: World) -> None:
    for who in ("Ann", "Annie", "Bob", "Anna_%"):
        world.call("GET", "/v1/me", who)
    assert world.call("GET", "/v1/players?q=a", "Bob") == []  # (two characters at least)
    found = world.call("GET", "/v1/players?q=an", "Bob")
    assert [p["name"] for p in found] == ["Ann", "Anna_%", "Annie"]
    assert all(p["relation"] == "none" and p["presence"] is None for p in found)
    assert [p["name"] for p in world.call("GET", "/v1/players?q=ANNA_%", "Bob")] == ["Anna_%"]
    assert [p["name"] for p in world.call("GET", "/v1/players?q=an", "Ann")] == ["Anna_%", "Annie"]  # (not you)


def test_blocking_ends_everything_between_two_players(world: World) -> None:
    world.friends("Ann", "Bob")
    world.call("GET", "/v1/me", "Cy")
    world.call("POST", "/v1/friends/requests", "Cy", {"to": "ann"})
    direct = world.call("POST", "/v1/conversations/direct", "Ann", {"player": "bob"})
    world.hub.clear()

    blocked = world.call("PUT", "/v1/blocks/bob", "Ann")
    assert blocked["relation"] == "blocked"
    assert world.call("GET", "/v1/friends", "Bob") == []
    assert world.hub.to("bob", "friend_removed")[0].data.id == "ann"
    assert world.call("GET", f"/v1/conversations/{direct['id']}", "Bob")["can_send"] is False
    assert world.call("POST", "/v1/friends/requests", "Bob", {"to": "ann"}, status=403)["code"] == "cant_add"
    assert world.call("POST", "/v1/friends/requests", "Ann", {"to": "bob"}, status=403)["code"] == "cant_add"
    assert world.call("GET", "/v1/players?q=an", "Bob") == []  # (Ann can't be found by Bob)
    assert [b["id"] for b in world.call("GET", "/v1/blocks", "Ann")] == ["bob"]
    # a pending request is ended too
    world.call("PUT", "/v1/blocks/cy", "Ann")
    assert world.call("GET", "/v1/friends/requests", "Cy") == []
    assert world.hub.to("cy", "friend_request")[-1].data.status == "declined"
    assert world.call("PUT", "/v1/blocks/ann", "Ann", status=422)["code"] == "self"

    world.call("DELETE", "/v1/blocks/bob", "Ann", status=204)
    assert world.call("GET", "/v1/blocks", "Ann")[0]["id"] == "cy"
    assert world.call("GET", "/v1/players/bob", "Ann")["relation"] == "none"  # (not friends again)
    assert world.call("POST", "/v1/friends/requests", "Bob", {"to": "ann"}, status=201)["status"] == "pending"


def test_friend_requests_are_limited(world: World) -> None:
    world.call("GET", "/v1/me", "Ann")
    for i in range(REQUESTS_PER_DAY + 1):
        world.call("GET", "/v1/me", f"P{i}")
    for i in range(REQUESTS_PER_DAY):
        world.call("POST", "/v1/friends/requests", "Ann", {"to": f"p{i}"}, status=201)
    r = world.call("POST", "/v1/friends/requests", "Ann", {"to": f"p{REQUESTS_PER_DAY}"}, status=429)
    assert r["code"] == "too_many_requests"
    world.clock.advance(days=1, seconds=1)
    for i in range(REQUESTS_PER_DAY, MAX_PENDING_SENT):
        world.call("GET", "/v1/me", f"P{i}")
        world.call("POST", "/v1/friends/requests", "Ann", {"to": f"p{i}"}, status=201)
    world.call("GET", "/v1/me", "Last")
    assert world.call("POST", "/v1/friends/requests", "Ann", {"to": "last"}, status=429)["code"] == \
        "too_many_requests"


def test_profile_pictures(world: World) -> None:
    from tests.unit.test_images import png
    world.friends("Ann", "Bob")
    world.call("GET", "/v1/me", "Cy")
    assert world.client.get("/v1/avatars/ann").status_code == 404
    world.hub.clear()
    picture = png(64, 64)
    r = world.client.put("/v1/me/avatar", content=picture, headers={**world.h("Ann"), "Content-Type": "image/png"})
    assert r.status_code == 200, r.text
    version = r.json()["avatar"]
    assert version and world.call("GET", "/v1/me", "Ann")["avatar"] == version
    # friends see it at once; everyone sees it on Ann
    assert [e.data.avatar for e in world.hub.to("bob", "friend")] == [version]
    assert world.call("GET", "/v1/friends", "Bob")[0]["avatar"] == version
    assert world.call("GET", "/v1/players/ann", "Cy")["avatar"] == version
    conv = world.call("POST", "/v1/conversations/direct", "Bob", {"player": "ann"})["id"]
    message = world.call("POST", f"/v1/conversations/{conv}/messages", "Ann", {"text": "new pic"})
    assert message["sender"]["avatar"] == version
    assert {m["id"]: m["avatar"] for m in world.call("GET", f"/v1/conversations/{conv}", "Bob")["members"]} == \
        {"ann": version, "bob": None}

    # anyone may load it (an <img> sends no token); with its version it is kept for good
    got = world.client.get(f"/v1/avatars/ann?v={version}")
    assert got.status_code == 200 and got.content == picture and got.headers["content-type"] == "image/png"
    assert "immutable" in got.headers["cache-control"] and got.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in got.headers["content-security-policy"]
    assert "immutable" not in world.client.get("/v1/avatars/ann").headers["cache-control"]

    for body, kind in ((b'<svg onload="alert(1)"/>', "image/svg+xml"), (b"x" * (300 * 1024), "image/png")):
        r = world.client.put("/v1/me/avatar", content=body, headers={**world.h("Cy"), "Content-Type": kind})
        assert r.status_code == 422 and r.json()["code"] == "invalid_image"
    world.clock.advance(seconds=1)
    as_png = {**world.h("Ann"), "Content-Type": "image/png"}
    second = world.client.put("/v1/me/avatar", content=png(32, 32), headers=as_png)
    assert second.json()["avatar"] > version  # (a new version: no cache keeps the old one)
    assert world.call("DELETE", "/v1/me/avatar", "Ann")["avatar"] is None
    assert world.client.get("/v1/avatars/ann").status_code == 404
