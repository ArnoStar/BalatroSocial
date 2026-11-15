"""Request bodies (pydantic), converted to the application's DTOs with ``to_dto()``."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from balatro_social.application.dto import (
    ActivityInput,
    ConversationChanges,
    MeChanges,
    NewGroup,
    NewMessage,
    NewRequest,
    SeedInput,
)
from balatro_social.domain import MAX_GROUP_MEMBERS, MAX_TEXT, ActivityKind, RequestPolicy

ID = Field(min_length=1, max_length=100)


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MeChangesBody(Body):
    requests: RequestPolicy | None = Field(None, description="who may send you friend requests: everyone, or only "
                                                             "with your friend code (code)")
    show_presence: bool | None = Field(None, description="your friends see when you are online and what you play")

    def to_dto(self) -> MeChanges:
        return MeChanges(requests=self.requests, show_presence=self.show_presence)


class ActivityBody(Body):
    kind: ActivityKind
    deck: str | None = Field(None, max_length=40, description="a run's deck (b_red ...)")
    stake: int | None = Field(None, ge=1, le=8)
    ante: int | None = Field(None, ge=0, le=10_000)
    seeded: bool = False
    challenge: str | None = Field(None, max_length=60)

    def to_dto(self) -> ActivityInput:
        return ActivityInput(kind=self.kind, deck=self.deck, stake=self.stake, ante=self.ante, seeded=self.seeded,
                             challenge=self.challenge)


class PresenceBody(Body):
    activity: ActivityBody | None = Field(None, description="what the player does in the game (null: nothing yet)")


class RequestBody(Body):
    to: str | None = Field(None, min_length=1, max_length=100, description="the player's id")
    code: str | None = Field(None, min_length=1, max_length=20, description="or their friend code (ABCD-2345)")

    @model_validator(mode="after")
    def one_target(self) -> RequestBody:
        if (self.to is None) == (self.code is None):
            raise ValueError("give the player's id (to) or their friend code (code)")
        return self

    def to_dto(self) -> NewRequest:
        return NewRequest(to=self.to, code=self.code)


class DirectBody(Body):
    player: str = ID


class GroupBody(Body):
    title: str = Field(min_length=1, max_length=200)
    members: list[str] = Field(min_length=1, max_length=MAX_GROUP_MEMBERS, description="friends of yours")

    def to_dto(self) -> NewGroup:
        return NewGroup(title=self.title, members=tuple(self.members))


class ConversationChangesBody(Body):
    title: str | None = Field(None, min_length=1, max_length=200, description="a group's")
    muted: bool | None = None

    def to_dto(self) -> ConversationChanges:
        return ConversationChanges(title=self.title, muted=self.muted)


class MembersBody(Body):
    players: list[str] = Field(min_length=1, max_length=MAX_GROUP_MEMBERS)


class SeedBody(Body):
    seed: str = Field(min_length=1, max_length=20)
    deck: str = Field(min_length=1, max_length=40)
    stake: int = Field(ge=1, le=8)


class MessageBody(Body):
    text: str | None = Field(None, max_length=MAX_TEXT * 2, description="the text, or a note with a run or a seed")
    run: str | None = Field(None, min_length=1, max_length=100, description="one of your runs (its game API id)")
    seed: SeedBody | None = None

    def to_dto(self) -> NewMessage:
        seed = SeedInput(seed=self.seed.seed, deck=self.seed.deck, stake=self.seed.stake) if self.seed else None
        return NewMessage(text=self.text, run=self.run, seed=seed)


class ReadBody(Body):
    seq: int = Field(ge=0, description="the last message read")
