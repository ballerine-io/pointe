"""A backchannel ("mm-hm", "uh-huh") while a session works is an acknowledgment: the voice stays quiet.

From the conversation suite: "Mmhmm." said while granary worked got "granary is still working on it. It's looking through
the repo and has opened the load file. There's more if you want it." The acknowledgment list had "okay" and "thanks"
but no backchannel sounds, so the brain was asked for a reply.

uv run pytest -q tests/test_backchannel_ack.py
"""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

from guards import ack_only  # noqa: E402


@pytest.mark.parametrize("said", ["Mmhmm.", "Mm-hmm.", "Mhm.", "Mm hmm", "Uh-huh.", "uh huh", "I see.", "Mm-hm, okay.", "אהה"])
def test_backchannels_are_acknowledgments(said):
    assert ack_only(said)


@pytest.mark.parametrize("said", ["Hmm, wait.", "Uh, what?", "Mm-hm, and run the tests.", "Yes."])
def test_these_ask_for_something(said):
    assert not ack_only(said)
