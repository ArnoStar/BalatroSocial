"""Errors of the application (who may call what, and the services it needs)."""

from __future__ import annotations

from balatro_social.domain import DomainError


class NotAuthenticated(DomainError):
    code = "unauthenticated"


class AuthUnavailable(DomainError):
    code = "auth_unavailable"


class GameApiUnavailable(DomainError):
    """The game API (a shared run's summary) can't be reached."""

    code = "game_api_unavailable"


class RunNotFound(DomainError):
    """The run to share isn't one of the caller's (the game API says so)."""

    code = "run_not_found"

    def __init__(self, run_id: str) -> None:
        super().__init__(f"no run {run_id!r} of yours")
