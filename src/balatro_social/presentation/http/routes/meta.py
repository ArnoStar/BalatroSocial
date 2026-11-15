from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from balatro_social import __version__

router = APIRouter(tags=["meta"])


@router.get("/health", summary="Is the service up")
def health(request: Request) -> dict[str, Any]:
    uses = request.app.state.use_cases
    return {"status": "ok", "version": __version__,
            "auth": "required" if uses.authenticate.authenticator.required else "off"}
