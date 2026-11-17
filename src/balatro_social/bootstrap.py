"""The composition root: picks the adapters and builds the use cases."""

from __future__ import annotations

import logging

from .application.ports import (
    Authenticator,
    Clock,
    CodeSource,
    EventHub,
    IdGenerator,
    MatchSource,
    Presence,
    RunSource,
    Store,
)
from .application.use_cases import Deps, UseCases, build
from .config import Settings
from .infrastructure.auth import AnonymousAuthenticator, JwtAuthenticator
from .infrastructure.game_api import GameApi
from .infrastructure.hub import LocalHub
from .infrastructure.persistence import MemoryStore, PostgresStore
from .infrastructure.presence import PresenceBoard
from .infrastructure.system import SecretCodes, SystemClock, UuidGenerator

log = logging.getLogger(__name__)


def build_authenticator(settings: Settings) -> Authenticator:
    if settings.auth_jwks_url and settings.auth_issuer:
        return JwtAuthenticator.from_jwks_url(settings.auth_jwks_url, settings.auth_issuer, settings.auth_audience)
    log.warning("sign-in is off (BALATRO_SOCIAL_AUTH_JWKS_URL is not set): every caller is the same player")
    return AnonymousAuthenticator()


def build_store(settings: Settings) -> Store:
    if settings.database == "memory":
        return MemoryStore()
    return PostgresStore(settings.database)


def build_use_cases(settings: Settings, *, store: Store | None = None, runs: RunSource | None = None,
                    hub: EventHub | None = None, presence: Presence | None = None, clock: Clock | None = None,
                    ids: IdGenerator | None = None, codes: CodeSource | None = None,
                    authenticator: Authenticator | None = None, matches: MatchSource | None = None) -> UseCases:
    game_api = GameApi(settings.api_url)
    deps = Deps(store=store if store is not None else build_store(settings), runs=runs or game_api,
                hub=hub or LocalHub(), presence=presence or PresenceBoard(), clock=clock or SystemClock(),
                ids=ids or UuidGenerator(), codes=codes or SecretCodes(), matches=matches or game_api)
    return build(deps, authenticator or build_authenticator(settings))
