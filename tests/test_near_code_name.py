""""Add a comment above the group rows" for a session whose code has dedupe_rows says so to the session.

Tester round 6 (rec-03, babble noise): "dedupe rows" was heard "the group rows" in 3 of 5 samples, sent as heard with
no note, and the session edited the wrong function in 2 of 5. Words in a code place ("above", "in", "to" ...) that are
not a name in the code, when exactly one name there ends the same way, get the closest name in the relay's note. The
message is not changed: the session decides, and asks if unsure.

uv run pytest -q tests/test_near_code_name.py
"""

import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import relay  # noqa: E402

CODE = {"dedupe_rows", "load_batches", "run_import"}


def test_words_in_a_code_place_that_are_no_name_get_the_closest_one():
    said = "Well, lantern to add a comment above the group rows."
    out = relay.as_heard("Add a comment above the group rows.", said, CODE)
    assert out.startswith("Add a comment above the group rows.")  # the request itself is as heard
    assert '"group rows" is not a name in this code' in out and "dedupe_rows" in out


def test_a_name_the_code_has_gets_no_note():
    out = relay.as_heard("Add a comment above dedupe rows.", "add a comment above dedupe rows", CODE)
    assert out == "Add a comment above dedupe rows."


def test_no_name_or_two_names_ending_the_same_way_get_no_note():
    assert relay.as_heard("Add a test for the header rows.", "add a test for the header rows", {"load_batches"}) == \
        "Add a test for the header rows."
    two = CODE | {"count_rows"}
    assert relay.as_heard("Add a comment above the group rows.", "add a comment above the group rows", two) == \
        "Add a comment above the group rows."


def test_words_not_in_a_code_place_get_no_note():
    assert relay.as_heard("The group rows look wrong, why?", "the group rows look wrong why", CODE) == \
        "The group rows look wrong, why?"


def test_a_new_name_the_user_gives_gets_no_closest_name():
    out = relay.as_heard("Rename calc to compute tax.", "rename calc to compute tax", {"calc_tax"})
    assert "closest" not in out
