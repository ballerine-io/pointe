"""A sentence that points back with "it" belongs to the session the sentence before it named.

From the conversation suite: "Let's work on atlas. What's its biggest file?" was refused as "the user named no session
for this part", then went out on a second try with a switch the user never asked for, and the voice said "My first
attempt didn't go through". A part with no session name of its own and a pronoun ("its", "it", "there") is about the
one session the part before it named.

uv run pytest -q tests/test_pronoun_part.py
"""

import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import add, d  # noqa: E402,F401  (d is the daemon fixture)


def _two(d):  # noqa: F811
    add(d, "b", "ledgerline")
    add(d, "a", "skyway")
    d.REGISTRY.mode = "orchestrator"


def test_its_points_back_to_the_session_just_named(d):  # noqa: F811
    _two(d)
    d.state.last_utterance = "Let's work on skyway. What's its biggest file?"
    assert d._unnamed_part("What is the biggest file in this repo?") is None


def test_a_part_with_its_own_subject_is_still_unnamed(d):  # noqa: F811
    _two(d)
    d.state.last_utterance = "Ledgerline adds a marker file. The other one checks the versions."
    assert d._unnamed_part("Check the versions.") == "The other one checks the versions."


def test_a_part_that_only_addresses_a_session_hands_it_the_next_part(d):  # noqa: F811
    """From the suite: "תגיד ל-granary. להוסיף docstring לפונקציה dedupeRows." was split at the pause, and the second
    sentence was refused as naming no session; the first only said whom it was for."""
    _two(d)
    d.state.last_utterance = "תגיד ל-skyway. להוסיף docstring לפונקציה dedupeRows."
    assert d._unnamed_part("Add a docstring to the function dedupeRows.") is None
    d.state.last_utterance = "Tell skyway. Add a docstring to load batches."
    assert d._unnamed_part("Add a docstring to load batches.") is None


def test_an_and_inside_the_request_does_not_split_it_from_its_session(d):  # noqa: F811
    """From the suite: "Tell atlas to add width and height attributes to the hero image." was split at "and", and the
    message, which carries both halves, was refused as naming no session."""
    _two(d)
    d.state.last_utterance = "Tell skyway to add width and height attributes to the hero image."
    assert d._unnamed_part("Add width and height attributes to the hero image.") is None
