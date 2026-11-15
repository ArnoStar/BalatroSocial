"""The FastAPI application."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from balatro_social import __version__
from balatro_social.application.use_cases import UseCases

from . import errors
from .routes import conversations, events, friends, me, meta, players

DESCRIPTION = """
Friends and chat for Balatro in the browser: friend requests (by name, or by
friend code and invite link), blocking, direct and group conversations in real
time, runs and seeds shared in them, and presence (who is online, and what they
play), for friends only.

`GET /v1/events` is a stream of server-sent events: what changes for the caller
(new messages, read receipts, typing, friend requests, presence). With sign-in
on, every route but `/health` needs an access token from the identity service.
"""

log = logging.getLogger(__name__)

SETTLE_EVERY = 3.0  # seconds: how often players who went offline are announced


async def settle_presence(use_cases: UseCases, every: float) -> None:
    while True:
        await asyncio.sleep(every)
        try:
            await asyncio.to_thread(use_cases.settle_presence)
        except Exception:
            log.exception("presence couldn't be settled")


def create_app(use_cases: UseCases, cors_origins: Sequence[str] = ("*",), heartbeat: float = 20) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(settle_presence(use_cases, SETTLE_EVERY))
        yield
        task.cancel()

    app = FastAPI(title="Balatro social", version=__version__, description=DESCRIPTION, lifespan=lifespan)
    app.state.use_cases = use_cases
    app.state.heartbeat = heartbeat
    app.add_middleware(CORSMiddleware, allow_origins=list(cors_origins), allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["Location", "WWW-Authenticate"])
    errors.install(app)
    for module in (meta, me, players, friends, conversations, events):
        app.include_router(module.router)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("docs")

    return app
