from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from balatro_social.application.dto import Player
from balatro_social.application.use_cases import UseCases
from balatro_social.bootstrap import build_use_cases
from balatro_social.config import Settings
from balatro_social.infrastructure.auth import JwtAuthenticator
from balatro_social.infrastructure.persistence import MemoryStore, PostgresStore
from balatro_social.infrastructure.presence import PresenceBoard
from balatro_social.presentation.http import create_app
from tests.fakes import Clock, Codes, FakeRuns, Ids, RecordingHub
from tests.tokens import AUDIENCE, ISSUER, FixedKeys, token

# a PostgreSQL database the tests may use (each test gets its own schema, dropped
# after it); without it the PostgreSQL tests are skipped. `make test` sets it to
# the database of `make db`.
PG_URL = os.environ.get("BALATRO_SOCIAL_TEST_DATABASE_URL")

HEARTBEAT = 0.05


@dataclass
class World:
    uses: UseCases
    runs: FakeRuns
    clock: Clock
    hub: RecordingHub
    presence: PresenceBoard
    client: TestClient
    headers: dict[str, dict[str, str]] = field(default_factory=dict)

    def h(self, who: str) -> dict[str, str]:
        """The Authorization header of a player named ``who`` (id = name in lower case)."""
        if who not in self.headers:
            self.headers[who] = {"Authorization": f"Bearer {token(sub=who.lower(), name=who)}"}
        return self.headers[who]

    def p(self, who: str) -> Player:
        return Player(id=who.lower(), name=who)

    def call(self, method: str, path: str, who: str, json: Any = None, status: int | None = None) -> Any:
        r = self.client.request(method, path, json=json, headers=self.h(who))
        if status is not None:
            assert r.status_code == status, r.text
        elif r.status_code >= 400:
            raise AssertionError(f"{method} {path} -> {r.status_code} {r.text}")
        return r.json() if r.content and r.headers.get("content-type", "").endswith("json") else None

    def friends(self, a: str, b: str) -> None:
        """Makes the two friends (each comes once first, so that the other can find them)."""
        for who in (a, b):
            self.call("GET", "/v1/me", who)
        req = self.call("POST", "/v1/friends/requests", a, {"to": b.lower()})
        self.call("POST", f"/v1/friends/requests/{req['id']}/accept", b)


def make_world(store: object | None = None, signed_in: bool = True) -> World:
    runs, clock, hub, presence = FakeRuns(), Clock(), RecordingHub(), PresenceBoard()
    auth = JwtAuthenticator(FixedKeys(), ISSUER, AUDIENCE) if signed_in else None
    uses = build_use_cases(Settings(database="memory", heartbeat=HEARTBEAT),
                           store=store or MemoryStore(), runs=runs, hub=hub,  # type: ignore[arg-type]
                           presence=presence, clock=clock, ids=Ids(), codes=Codes(), authenticator=auth,
                           matches=runs)
    return World(uses=uses, runs=runs, clock=clock, hub=hub, presence=presence,
                 client=TestClient(create_app(uses, heartbeat=HEARTBEAT)))


@pytest.fixture
def world() -> World:
    return make_world()


@pytest.fixture
def pg() -> Iterator[Callable[[], PostgresStore]]:
    if not PG_URL:
        pytest.skip("BALATRO_SOCIAL_TEST_DATABASE_URL is not set")
    schema = f"test_{uuid.uuid4().hex[:12]}"
    made: list[PostgresStore] = []

    def make() -> PostgresStore:
        made.append(PostgresStore(PG_URL, schema=schema))  # type: ignore[arg-type]
        return made[-1]

    yield make
    for s in made:
        s.close()
    with psycopg.connect(PG_URL, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
