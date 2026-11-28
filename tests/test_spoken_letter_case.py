"""A letter said aloud has no case: it reaches the session in lower case, or as the code writes it.

From HLK at 0.8.5 (bench/conversational/hlk/results/hlk-20261125-170854): the recognizer writes a letter said on its own
as a capital, and the relay passed it on as a literal. "Ends in s, like ninety s" reached the session as 'ending in
"S", e.g. "90S"', and the session made the function accept only an upper-case S: 8 of 9 twin-symbols runs failed their
hidden test on "90s" (the keyboard: 9 of 9). "Dunder, spelled G, I, M, B, A, L" became __GIMBAL__ (spelled-out-2, 2 of
3), and the field "t s" became TS, which the second session did not find in its code, where it is ts (two-repo-handoff-2).
A capital stays when the user said one ("all caps", "capital"), or when the code writes it that way.

uv run --locked --group test-tools pytest -q tests/test_spoken_letter_case.py
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import relay  # noqa: E402
from test_orchestrator import add, d, open_gates, record_dispatch  # noqa: E402,F401  (d is a fixture)

TWIN = 'Fix parse_retry_after so it also accepts a value ending in "S", e.g. "90S", which should return 90.'


@pytest.mark.parametrize("said", [
    "In retry dot py, fix parse retry after so it also accepts a value that ends in S, like 90S, which should give 90.",
    "In retry dot py, fix parse retry after so it also accepts a value that ends in s, like ninety s, which should give 90.",
    "In retry dot py, fix parse retry after so it also accepts a value that ends in S, like 90 S, which should give 90.",
])
def test_a_letter_said_on_its_own_is_lower_case(said):
    assert relay.letter_case(TWIN, said, set()) == \
        'Fix parse_retry_after so it also accepts a value ending in "s", e.g. "90s", which should return 90.'


def test_a_name_spelled_letter_by_letter_is_lower_case():
    said = "In limits dot py, add a module level variable, dunder, spelled G, I, M, B, A, L, so double underscore on " \
           "both sides, set to 9."
    message = "In limits.py, add a module-level variable named __GIMBAL__ (G-I-M-B-A-L, double underscores on both " \
              "sides), set to 9."
    assert relay.letter_case(message, said, {"MAX_USERS"}) == \
        "In limits.py, add a module-level variable named __gimbal__ (g-i-m-b-a-l, double underscores on both sides), set to 9."


@pytest.mark.parametrize("said", ["Tell marlin to rename the record field TS to timestamp in make record.",
                                  "Tell marlin to rename the record field t s to timestamp in make record."])
def test_letters_the_code_writes_in_lower_case_are_written_so(said):
    words = {"make_record", "key", "amount", "ts"}
    assert relay.letter_case("Rename the record field TS to timestamp in make_record.", said, words) == \
        "Rename the record field ts to timestamp in make_record."
    assert relay.letter_case("Read `timestamp` instead of `TS` in reader.py.", said, words) == \
        "Read `timestamp` instead of `ts` in reader.py."


@pytest.mark.parametrize("message,said,words", [
    # the user said the case
    ("In limits.py, add a constant QUORUM_BRINE = 3.",
     "In limits dot py, add a constant, all caps, spelled Q, U, O, R, U, M, then an underscore, then B, R, I, N, E, "
     "set to three.", set()),
    ('Accept a value ending in a capital "S".', "accept a value that ends in capital S", set()),
    # an acronym the code has, or one nobody spelled
    ("Round to 0 decimals when the currency is JPY.", "round to 0 decimals when the currency is JPY", {"JPY", "convert"}),
    ("Round to 0 decimals when the currency is JPY.", "round to 0 decimals when the currency is JPY", set()),
    # the code has the capital form
    ("Rename the field TS to timestamp.", "rename the field t s to timestamp", {"TS", "ts"}),
    # a capital letter the user never said, and the pronoun
    ("Pick option B.", "pick the second option", set()),
    ("Ask it why I see a 404 there.", "ask it why I see a 404 there", set()),
    ('Strip the trailing "S".', "it's the trailing one, don't keep it", set()),  # the s of "it's" is no letter said
    # a file name, and a word in capitals by convention, even where the code has it in lower case
    ("Add a line to README.md and close the TODO.", "add a line to the readme and close the to do", {"readme", "todo"}),
])
def test_a_capital_the_user_or_the_code_gave_stays(message, said, words):
    assert relay.letter_case(message, said, words) == message


def test_code_words_are_the_words_in_the_projects_source(tmp_path):
    (tmp_path / "reader.py").write_text('def owner_of(record):\n    return record["ts"]\n')
    (tmp_path / "notes.txt").write_text("TS everywhere\n")  # not source
    words = relay.code_words(str(tmp_path))
    assert {"owner_of", "record", "ts"} <= words and "TS" not in words


def test_the_send_writes_a_spoken_letter_in_lower_case(d, tmp_path, monkeypatch):  # noqa: F811
    (tmp_path / "retry.py").write_text('def parse_retry_after(value):\n    """Seconds, such as "30"."""\n    return int(value)\n')
    add(d, "k", "kiln", cwd=str(tmp_path))
    sent = record_dispatch(d, monkeypatch)
    open_gates(d, monkeypatch, "In retry dot py, fix parse retry after, the snake case one, so it also accepts a value "
                               "that ends in s, like ninety s, which should give ninety.")
    d.state.brain_target = "kiln"
    asyncio.run(d._send(TWIN))
    assert sent
    brief = sent[0][1].split("\n\n(Said by voice")[0]
    assert '"90s"' in brief and "90S" not in brief and 'ending in "s"' in brief
