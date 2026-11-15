from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from starlette.concurrency import run_in_threadpool

from balatro_social.application.dto import MeView
from balatro_social.domain import MAX_AVATAR_BYTES, InvalidImage
from balatro_social.presentation.http.deps import CurrentPlayer, Uses
from balatro_social.presentation.http.schemas import MeChangesBody, PresenceBody

router = APIRouter(prefix="/v1/me", tags=["you"])


@router.get("", response_model=MeView, summary="You: your friend code, settings and counts")
def me(player: CurrentPlayer, uses: Uses) -> MeView:
    """Your friend code (others add you with it), who may send you friend requests, whether your friends
    see you online, and how many friends, waiting requests and unread messages you have."""
    return uses.me(player)


@router.patch("", response_model=MeView, summary="Change your settings")
def update_me(body: MeChangesBody, player: CurrentPlayer, uses: Uses) -> MeView:
    return uses.update_me(player, body.to_dto())


@router.post("/code", response_model=MeView, summary="A new friend code")
def new_code(player: CurrentPlayer, uses: Uses) -> MeView:
    """The old code, and the invite links with it, stop working."""
    return uses.new_code(player)


IMAGE_BODY = {"requestBody": {"required": True, "content": {
    t: {"schema": {"type": "string", "format": "binary"}} for t in ("image/png", "image/jpeg", "image/webp")}}}


async def read_image(request: Request) -> bytes:
    """The request's body, refused as soon as it is larger than a picture may be."""
    too_big = InvalidImage(f"a profile picture is {MAX_AVATAR_BYTES // 1024} KB at most")
    if int(request.headers.get("content-length") or 0) > MAX_AVATAR_BYTES:
        raise too_big
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_AVATAR_BYTES:
            raise too_big
    return bytes(data)


@router.put("/avatar", response_model=MeView, summary="Your profile picture", openapi_extra=IMAGE_BODY)
async def set_avatar(request: Request, player: CurrentPlayer, uses: Uses) -> MeView:
    """The image itself as the body: PNG, JPEG or WebP, 256 KB and 1024 x 1024 pixels at most (the portal sends a
    256 x 256 WebP). Your friends see it at once; everyone may load it (``GET /v1/avatars/{id}``)."""
    data = await read_image(request)
    return await run_in_threadpool(uses.set_avatar, player, data)


@router.delete("/avatar", response_model=MeView, summary="No profile picture")
def remove_avatar(player: CurrentPlayer, uses: Uses) -> MeView:
    return uses.remove_avatar(player)


@router.put("/presence", status_code=status.HTTP_204_NO_CONTENT, summary="The game's heartbeat")
def presence(body: PresenceBody, player: CurrentPlayer, uses: Uses) -> Response:
    """The game says the player is in it, and what they do (in a run: its deck, stake and ante). Sent every
    minute and on each change: a player is online for 90 seconds after it. Friends are told."""
    uses.report_presence(player, body.activity.to_dto() if body.activity else None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
