from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response

from balatro_social.application.dto import PlayerView
from balatro_social.presentation.http.deps import CurrentPlayer, Uses

router = APIRouter(prefix="/v1", tags=["players"])


@router.get("/players", response_model=list[PlayerView], summary="Find players by name")
def find_players(player: CurrentPlayer, uses: Uses,
                 q: Annotated[str, Query(max_length=40, description="the start of a name (2 characters at least)")],
                 limit: Annotated[int, Query(ge=1, le=50)] = 20) -> list[PlayerView]:
    """Players who take friend requests from everyone, and your friends, whose name starts with ``q``;
    each with how they are related to you."""
    return uses.find_players(player, q, limit)


@router.get("/players/{player_id}", response_model=PlayerView, summary="A player")
def get_player(player_id: str, player: CurrentPlayer, uses: Uses) -> PlayerView:
    """Their name and how they are related to you; a friend's presence."""
    return uses.player(player, player_id)


@router.get("/avatars", summary="Which players have a profile picture")
def avatar_versions(uses: Uses,
                    ids: Annotated[str, Query(max_length=4000, description="account ids, separated by commas "
                                                                             "(the first 100 are looked up)")],
                    ) -> dict[str, int | None]:
    """Public, as the pictures are. Each id with its picture's version (``GET /v1/avatars/{id}?v=<version>``),
    or null: no picture (show their initials). Pages that name players (leaderboards, trades, the casino) show
    everyone's picture with one look-up."""
    return uses.avatar_versions(i.strip() for i in ids.split(","))


@router.get("/avatars/{player_id}", summary="A player's profile picture", response_class=Response,
            responses={200: {"content": {"image/webp": {}, "image/png": {}, "image/jpeg": {}}},
                       404: {"description": "no picture: show their initials"}})
def avatar(player_id: str, uses: Uses,
           v: Annotated[int | None, Query(description="its version (the views' `avatar`)")] = None) -> Response:
    """Public (an image is loaded without a token). With the right ``v`` it can be kept for good: a new picture
    has a new version."""
    image = uses.avatar(player_id)
    return Response(content=image.data, media_type=image.content_type, headers={
        "Cache-Control": "public, max-age=31536000, immutable" if v == image.version else "public, max-age=60",
        "ETag": f'"{image.version}"',
        # (an image, nothing else: no sniffing, no script, and not a page)
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Content-Disposition": "inline",
    })


@router.get("/codes/{code}", response_model=PlayerView, summary="Who a friend code is")
def player_by_code(code: str, player: CurrentPlayer, uses: Uses) -> PlayerView:
    """For an invite link (<site>/friends/add/<code>): the player to add."""
    return uses.player_by_code(player, code)
