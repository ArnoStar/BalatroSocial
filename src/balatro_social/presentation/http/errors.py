"""Errors as RFC 9457 problem details: ``{type, title, status, detail, code}``."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from balatro_social.application.errors import AuthUnavailable, GameApiUnavailable, NotAuthenticated, RunNotFound
from balatro_social.domain import (
    AlreadyFriends,
    AvatarNotFound,
    CantAdd,
    CantMessage,
    CodeNotFound,
    ConversationNotFound,
    DomainError,
    GroupFull,
    InvalidActivity,
    InvalidImage,
    InvalidMessage,
    InvalidSeed,
    InvalidTitle,
    MessageNotFound,
    NotAGroup,
    NotFriends,
    NotOwner,
    PlayerNotFound,
    RequestClosed,
    RequestNotFound,
    SelfAction,
    SlowDown,
    TooManyFriends,
    TooManyGroups,
    TooManyRequests,
)

log = logging.getLogger(__name__)

STATUS: list[tuple[type[DomainError], int]] = [
    (PlayerNotFound, 404),
    (CodeNotFound, 404),
    (RequestNotFound, 404),
    (ConversationNotFound, 404),
    (MessageNotFound, 404),
    (RunNotFound, 404),
    (AvatarNotFound, 404),
    (InvalidImage, 422),
    (SelfAction, 422),
    (InvalidMessage, 422),
    (InvalidTitle, 422),
    (InvalidSeed, 422),
    (InvalidActivity, 422),
    (CantAdd, 403),
    (NotFriends, 403),
    (CantMessage, 403),
    (NotOwner, 403),
    (AlreadyFriends, 409),
    (RequestClosed, 409),
    (NotAGroup, 409),
    (GroupFull, 409),
    (TooManyFriends, 409),
    (TooManyGroups, 409),
    (TooManyRequests, 429),
    (SlowDown, 429),
    (NotAuthenticated, 401),
    (AuthUnavailable, 503),
    (GameApiUnavailable, 503),
]
TITLES = {401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 409: "Conflict", 422: "Unprocessable Content",
          429: "Too Many Requests", 500: "Internal Server Error", 503: "Service Unavailable"}


def problem(status: int, code: str, detail: str, headers: dict[str, str] | None = None, **extra: Any) -> JSONResponse:
    body = {"type": f"https://balatro-social/errors/{code}", "title": TITLES.get(status, "Error"), "status": status,
            "detail": detail, "code": code, **extra}
    return JSONResponse(body, status_code=status, headers=headers, media_type="application/problem+json")


def install(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        status = next((s for cls, s in STATUS if isinstance(exc, cls)), 400)
        headers = {"WWW-Authenticate": 'Bearer error="invalid_token"'} if isinstance(exc, NotAuthenticated) else None
        return problem(status, exc.code, exc.message, headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return problem(422, "invalid_request", "the request doesn't match the schema", errors=errors)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unexpected error in %s %s", request.method, request.url.path, exc_info=exc)
        return problem(500, "internal_error", "unexpected server error")
