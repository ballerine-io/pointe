"""Night shift by voice on the words the ears really return, and a decision written as a sentence keeps its choice. QA
round 2: "tonightBilling adds ..." (Free start's ears) was no night shift, so billing's task went out at once; a DECIDED
line without arrows was stored as a question, and the briefing said "What it chose beyond that wasn't said"."""

import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import nightshift as ns  # noqa: E402
from test_night_shift import shift_of, started  # noqa: E402


def test_tonight_glued_to_the_next_word_still_opens_a_night_shift():
    assert ns.shift_intent("tonightBilling adds a marker file.") == "Billing adds a marker file."
    assert ns.shift_intent("Night shiftDocs checks the versions.") == "Docs checks the versions."
    assert ns.shift_intent("tonightly news") is None and ns.shift_intent("what did the night shift do") is None


def test_a_decision_written_as_a_sentence_keeps_it_as_the_choice():
    said = ("Treated the version the changelog states as its newest heading, since that is the only version it names. "
            "If you meant the README's, say so.")
    out = ns.read_report(f"NIGHT REPORT\nSTATUS: done\nDONE: versions checked\nDECIDED: {said}")
    question, choice, otherwise = out.decided[0]
    assert question == "" and choice.startswith("Treated the version") and otherwise == "say so."
    shift = shift_of(("docs", ["check the versions"]))
    (front,) = started(shift)
    shift.report(front, out, 1100.0)
    text = next(p["text"] for p in ns.morning(shift) if p["kind"] == "decided")
    assert "Treated the version the changelog states" in text and "not said" not in text


def test_the_arrow_form_is_unchanged():
    out = ns.read_report("NIGHT REPORT\nSTATUS: done\nDECIDED: cap the backoff? -> 30 seconds -> change MAX_BACKOFF")
    assert out.decided == [("cap the backoff?", "30 seconds", "change MAX_BACKOFF")]


def test_a_question_and_its_answer_in_one_sentence_are_split():
    assert ns._decision("Which timeout? Chose 30 seconds, as the support page says.") == (
        "Which timeout?", "Chose 30 seconds, as the support page says.", "")
