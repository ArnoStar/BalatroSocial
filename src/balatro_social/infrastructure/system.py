"""The clock, ids and friend codes."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from balatro_social.domain import new_code


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidGenerator:
    def new_id(self) -> str:
        return uuid.uuid4().hex


class SecretCodes:
    """Friend codes from the operating system's randomness: nobody can guess one."""

    def code(self) -> str:
        return new_code(secrets.choice)
