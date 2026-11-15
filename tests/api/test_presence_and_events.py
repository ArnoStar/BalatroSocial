"""Presence (friends only) and the event stream over HTTP."""

from __future__ import annotations

import json
import threading
import time
from datetime import timedelta
from typing import Any

from balatro_social.application.dto import NewMessage
from tests.conftest import World
from tests.tokens import token

RUN = {"kind": "run", "deck": "b_red", "stake": 3, "ante": 5}


def presence_of(world: World, viewer: str, player: str) -> Any:
    return next(f["presence"] for f in world.call("GET", "/v1/friends", viewer) if f["id"] == player)


def test_friends_see_what_a_player_plays(world: World) -> None:
    world.friends("Ann", "Bob")
    world.call("GET", "/v1/me", "Cy")
    world.hub.clear()
    world.call("PUT", "/v1/me/presence", "Ann", {"activity": RUN}, status=204)
    p = presence_of(world, "Bob", "ann")
    assert p["online"] and p["activity"] == {**RUN, "seeded": False, "challenge": None}
    assert [e.data.presence.online for e in world.hub.to("bob", "presence")] == [True]
    assert not world.hub.to("cy", "presence")
    assert world.call("GET", "/v1/players/ann", "Cy")["presence"] is None  # (not a friend)
    # the same activity again: nobody is told
    world.call("PUT", "/v1/me/presence", "Ann", {"activity": RUN}, status=204)
    assert len(world.hub.to("bob", "presence")) == 1
    r = world.call("PUT", "/v1/me/presence", "Ann", {"activity": {"kind": "run", "deck": "b_red"}}, status=422)
    assert r["code"] in ("invalid_activity", "invalid_request")

    # hidden: friends see Ann offline at once
    world.call("PATCH", "/v1/me", "Ann", {"show_presence": False})
    assert world.hub.to("bob", "presence")[-1].data.presence.online is False
    assert presence_of(world, "Bob", "ann") == {"online": False, "activity": None, "last_seen": None}
    world.call("PATCH", "/v1/me", "Ann", {"show_presence": True})
    assert presence_of(world, "Bob", "ann")["online"]

    # the game stops sending its heartbeat: offline after 90 seconds, with when she was last seen
    world.clock.advance(seconds=91)
    world.uses.settle_presence()
    assert world.hub.to("bob", "presence")[-1].data.presence.online is False
    p = presence_of(world, "Bob", "ann")
    assert not p["online"] and p["last_seen"] is not None


def frames(body: str) -> list[tuple[str, Any]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = block.split("\n")
        if lines[0].startswith(":"):
            out.append(("ping", None))
            continue
        event = lines[0].removeprefix("event: ")
        out.append((event, json.loads(lines[1].removeprefix("data: "))))
    return out


def test_the_event_stream(world: World) -> None:
    world.friends("Ann", "Bob")
    conv = world.call("POST", "/v1/conversations/direct", "Ann", {"player": "bob"})["id"]
    world.hub.clear()
    # (the stream ends when its token expires: the test reads it whole)
    short = {"Authorization": f"Bearer {token(sub='bob', name='Bob', lifetime=timedelta(seconds=1.5))}"}

    def write_while_bob_listens() -> None:
        for _ in range(100):
            if world.hub.streams("bob"):
                break
            time.sleep(0.01)
        world.uses.send(world.p("Ann"), conv, NewMessage(text="you there?"))

    threading.Thread(target=write_while_bob_listens).start()
    r = world.client.get("/v1/events", headers=short)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["x-accel-buffering"] == "no"
    got = frames(r.text)
    assert got[0][0] == "hello" and got[0][1]["id"] == "bob" and got[0][1]["friends"] == 1
    events = [e for e, _ in got]
    assert "ping" in events and events[-1] == "expired"
    message = next(d for e, d in got if e == "message")
    assert message["text"] == "you there?" and message["sender"]["name"] == "Ann"

    # while it was open Bob was online for Ann; the stream is closed: offline once the grace is over
    assert [e.data.presence.online for e in world.hub.to("ann", "presence")] == [True]
    assert world.hub.streams("bob") == 0
    world.clock.advance(seconds=11)
    world.uses.settle_presence()
    assert [e.data.presence.online for e in world.hub.to("ann", "presence")] == [True, False]


def test_an_expired_token_opens_no_stream(world: World) -> None:
    old = {"Authorization": f"Bearer {token(sub='bob', name='Bob', lifetime=timedelta(seconds=-60))}"}
    r = world.client.get("/v1/events", headers=old)
    assert r.status_code == 401 and r.json()["code"] == "unauthenticated"
