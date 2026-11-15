"""Errors of the domain.  Each has a stable ``code`` that clients can rely on."""

from __future__ import annotations


class DomainError(Exception):
    code = "domain_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PlayerNotFound(DomainError):
    code = "player_not_found"

    def __init__(self, player_id: str) -> None:
        super().__init__(f"no player {player_id!r}")


class CodeNotFound(DomainError):
    code = "code_not_found"

    def __init__(self, code: str) -> None:
        super().__init__(f"no player has the friend code {code!r}")


class RequestNotFound(DomainError):
    code = "request_not_found"

    def __init__(self, request_id: str) -> None:
        super().__init__(f"no friend request {request_id!r}")


class ConversationNotFound(DomainError):
    """Also for a conversation the caller isn't in: others' conversations don't exist for them."""

    code = "conversation_not_found"

    def __init__(self, conversation_id: str) -> None:
        super().__init__(f"no conversation {conversation_id!r}")


class MessageNotFound(DomainError):
    code = "message_not_found"

    def __init__(self, message_id: str) -> None:
        super().__init__(f"no message {message_id!r}")


class SelfAction(DomainError):
    code = "self"


class CantAdd(DomainError):
    """The player doesn't take friend requests from the caller (their setting, or a block)."""

    code = "cant_add"


class AlreadyFriends(DomainError):
    code = "already_friends"


class NotFriends(DomainError):
    code = "not_friends"


class RequestClosed(DomainError):
    code = "request_closed"


class TooManyFriends(DomainError):
    code = "too_many_friends"


class TooManyRequests(DomainError):
    code = "too_many_requests"


class SlowDown(DomainError):
    """Too many messages in a short time."""

    code = "slow_down"


class CantMessage(DomainError):
    """A direct conversation whose players aren't friends any more (or one blocked the other)."""

    code = "cant_message"


class NotAGroup(DomainError):
    code = "not_a_group"


class NotOwner(DomainError):
    code = "not_owner"


class GroupFull(DomainError):
    code = "group_full"


class TooManyGroups(DomainError):
    code = "too_many_groups"


class InvalidMessage(DomainError):
    code = "invalid_message"


class InvalidTitle(DomainError):
    code = "invalid_title"


class InvalidSeed(DomainError):
    code = "invalid_seed"


class InvalidActivity(DomainError):
    code = "invalid_activity"


class InvalidImage(DomainError):
    code = "invalid_image"


class AvatarNotFound(DomainError):
    code = "avatar_not_found"

    def __init__(self, player_id: str) -> None:
        super().__init__(f"{player_id!r} has no profile picture")
