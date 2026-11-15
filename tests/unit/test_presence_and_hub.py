from __future__ import annotations

import asyncio
import threading

import pytest

from balatro_social.application.dto import Event
from balatro_social.domain import Activity, ActivityKind
from balatro_social.infrastructure.hub import LocalHub
from balatro_social.infrastructure.presence import PresenceBoard
from tests.fakes import T0, Clock

RUN = Activity(kind=ActivityKind.RUN, deck="b_red", stake=1, ante=2)


def test_a_stream_keeps_its_player_online_and_a_little_after() -> None:
    clock, board = Clock(), PresenceBoard()
    assert not board.state("ann", T0).online
    assert board.connect("ann", clock.now())  # came online
    assert not board.connect("ann", clock.now())  # (a second tab)
    board.disconnect("ann", clock.now())
    assert board.state("ann", clock.now()).online
    board.disconnect("ann", clock.now())
    clock.advance(seconds=5)
    assert board.state("ann", clock.now()).online and board.settle(clock.now()) == []  # (a new token, a new page)
    clock.advance(seconds=6)
    assert not board.state("ann", clock.now()).online
    assert board.settle(clock.now()) == ["ann"]
    assert board.settle(clock.now()) == []  # (once)


def test_the_games_heartbeat_says_what_the_player_does() -> None:
    clock, board = Clock(), PresenceBoard()
    assert board.beat("ann", None, clock.now())  # came online
    assert board.state("ann", clock.now()).activity is None
    assert board.beat("ann", RUN, clock.now())  # started a run
    assert not board.beat("ann", RUN, clock.now())  # (the same)
    assert board.state("ann", clock.now()).activity == RUN
    clock.advance(seconds=89)
    assert board.state("ann", clock.now()).online and board.settle(clock.now()) == []
    clock.advance(seconds=2)
    assert not board.state("ann", clock.now()).online
    assert board.settle(clock.now()) == ["ann"]


def test_closing_the_game_while_on_the_site_is_a_change() -> None:
    clock, board = Clock(), PresenceBoard()
    board.connect("ann", clock.now())
    board.beat("ann", RUN, clock.now())
    clock.advance(seconds=91)
    assert board.settle(clock.now()) == ["ann"]  # out of the game ...
    state = board.state("ann", clock.now())
    assert state.online and state.activity is None  # ... still on the site
    assert board.settle(clock.now()) == []


def test_the_hub_hands_events_to_the_streams_of_a_player() -> None:
    async def scenario() -> None:
        hub = LocalHub(queue_size=4)
        a, b = hub.subscribe("ann"), hub.subscribe("ann")
        other = hub.subscribe("bob")
        assert hub.streams("ann") == 2
        threading.Thread(target=hub.publish, args=(["ann"], Event("message", {"n": 1}))).start()
        assert (await a.next(1)) == Event("message", {"n": 1})
        assert (await b.next(1)) == Event("message", {"n": 1})
        assert (await other.next(0.05)) is None  # (nothing for bob: a heartbeat's time)
        a.close()
        assert hub.streams("ann") == 1
        with pytest.raises(EOFError):
            await a.next(0.05)
        for i in range(6):  # b doesn't read: it falls behind and is closed
            hub.publish(["ann"], Event("message", {"n": i}))
        await asyncio.sleep(0.01)
        with pytest.raises(EOFError):
            await b.next(1)
        assert hub.streams("ann") == 0

    asyncio.run(scenario())
