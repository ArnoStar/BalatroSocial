from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response, status

from balatro_social.application.dto import PlayerView, RequestView
from balatro_social.presentation.http.deps import CurrentPlayer, Uses
from balatro_social.presentation.http.schemas import RequestBody

router = APIRouter(prefix="/v1", tags=["friends"])


@router.get("/friends", response_model=list[PlayerView], summary="Your friends")
def friends(player: CurrentPlayer, uses: Uses) -> list[PlayerView]:
    """Online first (with what they play), then by name."""
    return uses.friends(player)


@router.delete("/friends/{friend_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a friend")
def remove_friend(friend_id: str, player: CurrentPlayer, uses: Uses) -> Response:
    """Your direct conversation stays, to read; nobody can write in it until you are friends again."""
    uses.remove_friend(player, friend_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/friends/requests", response_model=list[RequestView], summary="Friend requests waiting")
def requests(player: CurrentPlayer, uses: Uses,
             box: Annotated[Literal["incoming", "outgoing", "all"], Query()] = "all") -> list[RequestView]:
    return uses.requests(player, box)


@router.post("/friends/requests", status_code=status.HTTP_201_CREATED, response_model=RequestView,
             summary="Ask a player to be friends")
def send_request(body: RequestBody, player: CurrentPlayer, uses: Uses) -> RequestView:
    """By their id, or by their friend code (players who take requests only with their code). If they had
    asked you already, you are friends at once (the answer's status is accepted)."""
    return uses.send_request(player, body.to_dto())


@router.post("/friends/requests/{request_id}/accept", response_model=RequestView, summary="Accept a request")
def accept(request_id: str, player: CurrentPlayer, uses: Uses) -> RequestView:
    return uses.accept(player, request_id)


@router.post("/friends/requests/{request_id}/decline", response_model=RequestView, summary="Decline a request")
def decline(request_id: str, player: CurrentPlayer, uses: Uses) -> RequestView:
    return uses.decline(player, request_id)


@router.post("/friends/requests/{request_id}/cancel", response_model=RequestView, summary="Take your request back")
def cancel(request_id: str, player: CurrentPlayer, uses: Uses) -> RequestView:
    return uses.cancel(player, request_id)


@router.get("/blocks", response_model=list[PlayerView], summary="The players you blocked")
def blocks(player: CurrentPlayer, uses: Uses) -> list[PlayerView]:
    return uses.blocks(player)


@router.put("/blocks/{player_id}", response_model=PlayerView, summary="Block a player")
def block(player_id: str, player: CurrentPlayer, uses: Uses) -> PlayerView:
    """Ends your friendship and any request between you; they can't ask you again, nor write to you, and
    don't find you by name. Your old messages stay."""
    return uses.block(player, player_id)


@router.delete("/blocks/{player_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Unblock a player")
def unblock(player_id: str, player: CurrentPlayer, uses: Uses) -> Response:
    uses.unblock(player, player_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
