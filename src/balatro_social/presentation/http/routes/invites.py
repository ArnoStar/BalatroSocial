"""Invites to play a match together, and the inbox: what waits for the player (a notification bell)."""

from __future__ import annotations

from fastapi import APIRouter, status

from balatro_social.application.dto import InboxView, InviteView
from balatro_social.presentation.http.deps import CurrentPlayer, Uses
from balatro_social.presentation.http.schemas import InviteBody

router = APIRouter(prefix="/v1", tags=["invites"])


@router.post("/invites", status_code=status.HTTP_201_CREATED, response_model=InviteView,
             summary="Invite a friend to your match")
def send_invite(body: InviteBody, player: CurrentPlayer, uses: Uses) -> InviteView:
    """To the match you are in, waiting for players (the game API's ``/matches/current``, read with your token:
    ``409 no_open_match`` without one). Friends only. Your friend gets an ``invite`` event; they join with its
    ``code``. Again to the same friend and match: the same invite, open longer."""
    return uses.send_invite(player, body.to_dto())


@router.get("/invites", response_model=list[InviteView], summary="Your open invites")
def invites(player: CurrentPlayer, uses: Uses) -> list[InviteView]:
    return uses.invites(player)


@router.post("/invites/{invite_id}/accept", response_model=InviteView, summary="Take an invite")
def accept_invite(invite_id: str, player: CurrentPlayer, uses: Uses) -> InviteView:
    """Then join the match in the game with its ``code`` (<site>/play/?match=<code>)."""
    return uses.answer_invite(player, invite_id, True)


@router.post("/invites/{invite_id}/decline", response_model=InviteView, summary="Decline an invite")
def decline_invite(invite_id: str, player: CurrentPlayer, uses: Uses) -> InviteView:
    return uses.answer_invite(player, invite_id, False)


@router.get("/inbox", response_model=InboxView, summary="What waits for you")
def inbox(player: CurrentPlayer, uses: Uses) -> InboxView:
    """For a notification bell: friend requests to answer, conversations with unread messages (not muted) and
    open invites. Keep it up to date with the event stream (friend_request, message, read, invite)."""
    return uses.inbox(player)
