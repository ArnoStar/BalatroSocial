"""The rules and limits of friends and chat (pure functions)."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from datetime import timedelta

from .errors import InvalidActivity, InvalidMessage, InvalidSeed, InvalidTitle
from .model import Activity, ActivityKind, SeedCard

MAX_FRIENDS = 200
MAX_PENDING_SENT = 50  # friend requests waiting for an answer, sent by one player
REQUESTS_PER_DAY = 40  # friend requests one player may send in 24 hours
MAX_GROUP_MEMBERS = 20
MAX_GROUPS = 30  # groups one player is in
MAX_TEXT = 2000  # characters in a message
MAX_TITLE = 40  # characters in a group's title
MESSAGE_BURST = 20  # messages one player may send ...
MESSAGE_WINDOW = timedelta(seconds=30)  # ... in this long
PRESENCE_TTL = timedelta(seconds=90)  # a game's heartbeat keeps its player online this long

# friend codes: no 0/O, 1/I/L, so that a code read aloud or copied by hand works
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 8

SEED = re.compile(r"[A-Z0-9]{1,8}")  # the game's seeds: up to 8 letters and digits
DECK = re.compile(r"b_[a-z_]{1,30}")
CHALLENGE = re.compile(r"c_[a-z0-9_]{1,40}")
# bidirectional overrides and isolates: they could make a message read as something else
BIDI = {"‪", "‫", "‬", "‭", "‮", "⁦", "⁧", "⁨", "⁩"}


def new_code(pick: Callable[[str], str]) -> str:
    """A friend code; ``pick`` chooses one character of a string (the system's randomness)."""
    return "".join(pick(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def parse_code(text: str) -> str | None:
    """A friend code as typed or pasted ("abcd-2345", with spaces...), or None if it can't be one."""
    code = re.sub(r"[\s-]", "", text).upper()
    if len(code) != CODE_LENGTH or any(c not in CODE_ALPHABET for c in code):
        return None
    return code


def show_code(code: str) -> str:
    """ABCD-2345: easier to read out."""
    return f"{code[:4]}-{code[4:]}"


def pair_key(a: str, b: str) -> str:
    """The two players of a direct conversation, in one order."""
    return "|".join(sorted((a, b)))


def clean_text(text: str) -> str:
    """A message's text: control characters out, blank lines collapsed, 1 to MAX_TEXT characters."""
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = "".join(c for c in t if c in "\n\t" or (unicodedata.category(c) != "Cc" and c not in BIDI))
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    if not t:
        raise InvalidMessage("a message needs some text")
    if len(t) > MAX_TEXT:
        raise InvalidMessage(f"a message has at most {MAX_TEXT} characters")
    return t


def clean_note(text: str | None) -> str:
    """The text that comes with a shared run or seed: optional."""
    return clean_text(text) if text and text.strip() else ""


def clean_title(title: str) -> str:
    """A group's title: one line of 1 to MAX_TITLE characters."""
    t = " ".join("".join(c for c in title if unicodedata.category(c) != "Cc" and c not in BIDI).split())
    if not t:
        raise InvalidTitle("a group needs a title")
    if len(t) > MAX_TITLE:
        raise InvalidTitle(f"a group's title has at most {MAX_TITLE} characters")
    return t


def check_seed(seed: str, deck: str, stake: int) -> SeedCard:
    s = seed.strip().upper()
    if not SEED.fullmatch(s):
        raise InvalidSeed("a seed is 1 to 8 letters and digits")
    if not DECK.fullmatch(deck):
        raise InvalidSeed(f"no deck {deck!r}")
    if not 1 <= stake <= 8:
        raise InvalidSeed("the stake is 1 (White) to 8 (Gold)")
    return SeedCard(seed=s, deck=deck, stake=stake)


def check_activity(a: Activity) -> Activity:
    """What the game may say the player does: in a run, its deck, stake and ante."""
    if a.kind is not ActivityKind.RUN:
        return Activity(kind=a.kind)
    if a.deck is None or not DECK.fullmatch(a.deck):
        raise InvalidActivity("a run's activity has its deck (b_red ...)")
    if a.stake is None or not 1 <= a.stake <= 8:
        raise InvalidActivity("a run's activity has its stake, 1 to 8")
    if a.ante is not None and not 0 <= a.ante <= 10_000:
        raise InvalidActivity("an ante is 0 to 10000")
    if a.challenge is not None and not CHALLENGE.fullmatch(a.challenge):
        raise InvalidActivity(f"no challenge {a.challenge!r}")
    return a
