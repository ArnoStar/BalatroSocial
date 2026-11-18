from __future__ import annotations

import random

import pytest

from balatro_social.domain import (
    CODE_ALPHABET,
    MAX_TEXT,
    MAX_TITLE,
    Activity,
    ActivityKind,
    InvalidActivity,
    InvalidMessage,
    InvalidSeed,
    InvalidTitle,
    check_activity,
    check_seed,
    clean_note,
    clean_text,
    clean_title,
    new_code,
    pair_key,
    parse_code,
    show_code,
)


def test_friend_codes_are_easy_to_read_and_type() -> None:
    code = new_code(random.Random(1).choice)
    assert len(code) == 8 and all(c in CODE_ALPHABET for c in code)
    assert not set("01ILO") & set(CODE_ALPHABET)
    assert show_code("ABCD2345") == "ABCD-2345"
    for typed in ("ABCD-2345", "abcd2345", " abcd - 2345 ", "AB CD 23 45"):
        assert parse_code(typed) == "ABCD2345", typed
    for wrong in ("ABCD-234", "ABCD-23456", "ABCD-0123", "OOOO-IIII", ""):
        assert parse_code(wrong) is None, wrong


def test_a_messages_text_is_cleaned() -> None:
    assert clean_text("  hello\r\nthere  ") == "hello\nthere"
    assert clean_text("a\n\n\n\n\nb") == "a\n\nb"
    assert clean_text("x\x00\x07y‮z") == "xyz"  # control characters, a bidi override
    family = "\U0001f468‍\U0001f469‍\U0001f467"  # (the joiners stay: one emoji)
    assert clean_text(f"gg {family}") == f"gg {family}"
    assert clean_text("é" * MAX_TEXT) == "é" * MAX_TEXT
    for wrong in ("", "   \n\t ", "\x00", "x" * (MAX_TEXT + 1)):
        with pytest.raises(InvalidMessage):
            clean_text(wrong)
    assert clean_note(None) == clean_note("  ") == ""
    assert clean_note(" nice ") == "nice"


def test_a_groups_title_is_one_line() -> None:
    assert clean_title("  The \n Jimbos  ") == "The Jimbos"
    assert clean_title("x" * MAX_TITLE) == "x" * MAX_TITLE
    for wrong in ("", " \n ", "x" * (MAX_TITLE + 1)):
        with pytest.raises(InvalidTitle):
            clean_title(wrong)


def test_seeds() -> None:
    card = check_seed(" abc12345 ", "b_red", 8)
    assert (card.seed, card.deck, card.stake) == ("ABC12345", "b_red", 8)
    for seed, deck, stake in (("", "b_red", 1), ("ABCDEFGHI", "b_red", 1), ("AB-CD", "b_red", 1),
                              ("ABC", "red", 1), ("ABC", "b_red", 0), ("ABC", "b_red", 9)):
        with pytest.raises(InvalidSeed):
            check_seed(seed, deck, stake)


def test_activities() -> None:
    assert check_activity(Activity(kind=ActivityKind.MENU, deck="b_red", ante=3)) == Activity(kind=ActivityKind.MENU)
    pvp = Activity(kind=ActivityKind.RUN, deck="b_red", stake=1, mode="pvp")
    assert check_activity(pvp) == pvp
    with pytest.raises(InvalidActivity):
        check_activity(Activity(kind=ActivityKind.RUN, deck="b_red", stake=1, mode="duel"))
    run = Activity(kind=ActivityKind.RUN, deck="b_plasma", stake=5, ante=6, challenge="c_omelette_1")
    assert check_activity(run) == run
    for wrong in (Activity(kind=ActivityKind.RUN), Activity(kind=ActivityKind.RUN, deck="b_red"),
                  Activity(kind=ActivityKind.RUN, deck="b_red", stake=9),
                  Activity(kind=ActivityKind.RUN, deck="b_red", stake=1, challenge="nope")):
        with pytest.raises(InvalidActivity):
            check_activity(wrong)


def test_pairs() -> None:
    assert pair_key("bob", "alice") == pair_key("alice", "bob") == "alice|bob"
