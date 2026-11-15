from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from balatro_social.application.dto import ConversationView, MessageView
from balatro_social.presentation.http.deps import CurrentPlayer, Uses
from balatro_social.presentation.http.schemas import (
    ConversationChangesBody,
    DirectBody,
    GroupBody,
    MembersBody,
    MessageBody,
    ReadBody,
)

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationView], summary="Your conversations")
def conversations(player: CurrentPlayer, uses: Uses) -> list[ConversationView]:
    """Direct and group conversations, the last written to first, with their last message and your unread
    count."""
    return uses.conversations(player)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ConversationView, summary="Make a group")
def create_group(body: GroupBody, player: CurrentPlayer, uses: Uses) -> ConversationView:
    """With a title and some of your friends (20 players at most, you included). You are its owner."""
    return uses.create_group(player, body.to_dto())


@router.post("/direct", response_model=ConversationView, summary="Your conversation with a friend")
def open_direct(body: DirectBody, player: CurrentPlayer, uses: Uses) -> ConversationView:
    """Made the first time (only with a friend)."""
    return uses.open_direct(player, body.player)


@router.get("/{conversation_id}", response_model=ConversationView, summary="A conversation")
def conversation(conversation_id: str, player: CurrentPlayer, uses: Uses) -> ConversationView:
    return uses.conversation(player, conversation_id)


@router.patch("/{conversation_id}", response_model=ConversationView, summary="Rename a group, or mute it")
def update_conversation(conversation_id: str, body: ConversationChangesBody, player: CurrentPlayer,
                        uses: Uses) -> ConversationView:
    return uses.update_conversation(player, conversation_id, body.to_dto())


@router.post("/{conversation_id}/members", response_model=ConversationView, summary="Add friends to a group")
def add_members(conversation_id: str, body: MembersBody, player: CurrentPlayer, uses: Uses) -> ConversationView:
    """They read what is written from now on."""
    return uses.add_members(player, conversation_id, body.players)


@router.delete("/{conversation_id}/members/{member_id}", summary="Leave a group, or remove a player from it",
               responses={200: {"model": ConversationView}, 204: {"description": "you left"}})
def remove_member(conversation_id: str, member_id: str, player: CurrentPlayer, uses: Uses) -> Response:
    """Yourself: you leave (204). Someone else: the group's owner removes them (200, the group)."""
    view = uses.remove_member(player, conversation_id, member_id)
    if view is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return JSONResponse(jsonable_encoder(view))


@router.get("/{conversation_id}/messages", response_model=list[MessageView], summary="Messages")
def messages(conversation_id: str, player: CurrentPlayer, uses: Uses,
             before: Annotated[int | None, Query(ge=1, description="older than this message")] = None,
             after: Annotated[int | None, Query(ge=0, description="newer than this message")] = None,
             limit: Annotated[int, Query(ge=1, le=100)] = 50) -> list[MessageView]:
    """Oldest first: the last ``limit`` (before ``before``), or the first ``limit`` after ``after``."""
    return uses.messages(player, conversation_id, before, after, limit)


@router.post("/{conversation_id}/messages", status_code=status.HTTP_201_CREATED, response_model=MessageView,
             summary="Write, or share a run or a seed")
def send(conversation_id: str, body: MessageBody, player: CurrentPlayer, uses: Uses) -> MessageView:
    """``text``; or ``run`` (one of your runs, by its id: its summary is read from the game API now) or ``seed``
    (``{seed, deck, stake}``), each with an optional ``text``. 20 messages in 30 seconds at most."""
    return uses.send(player, conversation_id, body.to_dto())


@router.delete("/{conversation_id}/messages/{message_id}", response_model=MessageView,
               summary="Delete one of your messages")
def delete_message(conversation_id: str, message_id: str, player: CurrentPlayer, uses: Uses) -> MessageView:
    return uses.delete_message(player, conversation_id, message_id)


@router.post("/{conversation_id}/read", status_code=status.HTTP_204_NO_CONTENT, summary="Mark as read")
def mark_read(conversation_id: str, body: ReadBody, player: CurrentPlayer, uses: Uses) -> Response:
    """Up to message ``seq``: the others see it (read receipts)."""
    uses.mark_read(player, conversation_id, body.seq)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{conversation_id}/typing", status_code=status.HTTP_204_NO_CONTENT, summary="You are writing")
def typing(conversation_id: str, player: CurrentPlayer, uses: Uses) -> Response:
    """The others see "… is writing" for a few seconds: send it again every 3 seconds while writing."""
    uses.typing(player, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
