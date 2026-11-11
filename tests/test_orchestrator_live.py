"""Live checks of the orchestrator's model gates: routing, relevance, idle assessment.
RUN_LIVE=1 uv run pytest -q tests/test_orchestrator_live.py"""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harnesses.base import finished_tag  # noqa: E402

CC_FINISHED = finished_tag("claude-code")  # how a Claude Code session's turn end reaches the feed
pytestmark = pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="calls the Gemini API; set RUN_LIVE=1")

REPO_TEXT = "pricing.py has apply_discount and total; test_pricing.py has two tests."
NOTES_TEXT = "notes.md lists the product launch plan and dates."


@pytest.fixture
def daemon(tmp_path):
    (tmp_path / "token").write_text("t")
    os.environ["CLAUDE_VOICE_STATE"] = str(tmp_path)
    import vendors
    vendors.key("gemini")  # the environment first, then the Keychain, as the daemon reads it
    import daemon as d

    saved = (dict(d.REGISTRY.sessions), d.REGISTRY.active_id, d.REGISTRY.mode, d.REGISTRY.path)
    d.REGISTRY.path = None  # a test registry is never written anywhere
    yield d
    d.REGISTRY.sessions, d.REGISTRY.active_id, d.REGISTRY.mode, d.REGISTRY.path = saved
    d.state.last_utterance, d.state.sent, d.state.conversation = "", [], []


@pytest.fixture
def answers(monkeypatch):
    """Every raw model answer, so a failure shows what the model said."""
    from google.genai import models

    seen: list[str] = []
    original = models.AsyncModels.generate_content

    async def recording(self, *args, **kwargs):
        resp = await original(self, *args, **kwargs)
        seen.append(resp.text)
        return resp

    monkeypatch.setattr(models.AsyncModels, "generate_content", recording)
    return seen


def make(tmp: Path, name: str, text: str):
    from sessions import Session

    path = tmp / f"{name.replace('/', '_')}.jsonl"
    path.write_text(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}) + "\n")
    return Session(id=name, name=name, cwd=f"/tmp/{name.split('/')[0]}", pid=os.getpid(), transcript=str(path))


def use(d, sessions, active, mode="orchestrator"):
    d.REGISTRY.sessions = {s.id: s for s in sessions}
    d.REGISTRY.active_id, d.REGISTRY.mode = active.id, mode


def classify(d, said, request, sessions):
    d.state.last_utterance = said
    picked = asyncio.run(d._classify_target(request, sessions))
    return picked.name if picked else None


def relevant(d, proposed, said, earlier=(), conversation=()):
    return asyncio.run(d._is_current_request(proposed, said, list(earlier), list(conversation)))


class Params:
    def __init__(self, message):
        self.arguments, self.result = {"message": message}, None

    async def result_callback(self, result):
        self.result = result


# routing classifier

def test_L01_subject_routes_to_the_inactive_session(daemon, answers, tmp_path, monkeypatch):
    repo, notes = make(tmp_path, "cv-repo/main", REPO_TEXT), make(tmp_path, "cv-notes/main", NOTES_TEXT)
    use(daemon, [repo, notes], notes)
    assert classify(daemon, "run the pricing tests", "Run the pricing tests.", [repo, notes]) == "cv-repo/main", answers

    dispatched = []

    async def fake_dispatch(target, message):
        dispatched.append(target.name)
        return True

    monkeypatch.setattr(daemon, "_dispatch", fake_dispatch)
    daemon.state.last_utterance, daemon.state.last_user_speech_at = "run the pricing tests", time.time()
    daemon.state.last_delegation_at, daemon.state.sent, daemon.state.conversation = 0.0, [], []
    params = Params("Run the pricing tests.")
    asyncio.run(daemon.send_to_claude_code(params))
    assert params.result.get("routing") == "auto", (params.result, answers)
    assert dispatched == ["cv-repo/main"], (params.result, answers)
    assert "cv-repo/main" in params.result.get("say", ""), (params.result, answers)


def test_L02_follow_up_about_the_notes_routes_there(daemon, answers, tmp_path):
    repo, notes = make(tmp_path, "cv-repo/main", REPO_TEXT), make(tmp_path, "cv-notes/main", NOTES_TEXT)
    use(daemon, [repo, notes], repo)
    assert classify(daemon, "and what about in the notes, when is launch?", "When is the launch date in the notes?",
                    [repo, notes]) == "cv-notes/main", answers


def test_L03_overlapping_subjects_are_unclear(daemon, answers, tmp_path):
    py = make(tmp_path, "cv-py/main", "Ran pytest, 14 passed.")
    js = make(tmp_path, "cv-js/main", "Ran npm test, 3 failed.")
    use(daemon, [py, js], py)
    assert classify(daemon, "run the tests", "Run the tests.", [py, js]) in (None, "cv-py/main"), answers


@pytest.mark.parametrize("said,expected", [
    ("תגיד לבלובל להריץ טסטים", "bluebell/dev"),
    ("תגיד ללנטרן לעשות rebase", "river-lantern/main"),
])
def test_L04_hebrew_script_names(said, expected, daemon, answers, tmp_path):
    lark = make(tmp_path, "bluebell/dev", "Ran lint on ledger-api; two warnings left in the routes folder.")
    lantern = make(tmp_path, "river-lantern/main", "Wrote the cache migrations for the importer.")
    use(daemon, [lark, lantern], lark if expected != "bluebell/dev" else lantern)
    request = "Run the tests." if expected == "bluebell/dev" else "Rebase the branch."
    assert classify(daemon, said, request, [lark, lantern]) == expected, answers


@pytest.mark.parametrize("said,request_text,expected", [
    ("tell bluebell to update the pricing page", "Update the pricing page.", "bluebell/cfx-123-pricing"),
    ("tell bluebell to fix the lint config", "Fix the lint config.", "bluebell/dev"),
])
def test_L05_tie_between_same_named_sessions(said, request_text, expected, daemon, answers, tmp_path):
    dev = make(tmp_path, "bluebell/dev", "eslint config updated")
    pricing = make(tmp_path, "bluebell/cfx-123-pricing", "pricing page component refactor")
    other = pricing if expected == "bluebell/dev" else dev
    use(daemon, [dev, pricing], other)
    assert classify(daemon, said, request_text, [dev, pricing]) == expected, answers


def test_L06_long_session_names_come_back_whole(daemon, answers, tmp_path):
    docs = make(tmp_path, "maple-docs-2026/docs-refresh-pricing",
                "Refreshed the SDK pricing docs page and the FAQ.")
    lantern = make(tmp_path, "river-lantern/abc-42-wire-importer-entry",
                 "Wired the CSV importer entry point; the Driftwood uploader is untested.")
    use(daemon, [docs, lantern], docs)
    assert classify(daemon, "test the driftwood uploader in the importer entry",
                    "Add a test for the Driftwood uploader in the importer entry.",
                    [docs, lantern]) == lantern.name, answers


# relevance gate

DISCOUNT_TALK = [("user", "fix the discount bug and run the tests"), ("assistant", "On it.")]
DISCOUNT = "Fix the discount bug in pricing.py and run the tests."


@pytest.mark.parametrize("said", ["why didn't you send it?", "למה לא שלחת?"])
def test_L07_L08_complaint_unlocks_the_send(said, daemon, answers):
    assert relevant(daemon, DISCOUNT, said, [], DISCOUNT_TALK) is True, answers


SAME_TALK = [("user", "tell bluebell to run the tests"), ("assistant", "Sent to bluebell.")]


def test_L09_same_instruction_to_another_session(daemon, answers):
    assert relevant(daemon, "Run the tests.", "now tell lantern to do the same", ["bluebell/dev: Run the tests."],
                    SAME_TALK) is True, answers


def test_L10_a_replay_is_still_refused(daemon, answers):
    talk = SAME_TALK + [("user", "what is lantern doing?")]
    assert relevant(daemon, "Run the tests.", "what is lantern doing?", ["bluebell/dev: Run the tests."],
                    talk) is False, answers


@pytest.mark.parametrize("earlier", [[], ["bluebell/dev: Run the tests."]])
def test_L11_each_clause_of_a_two_target_utterance(earlier, daemon, answers):
    assert relevant(daemon, "Pull dev.", "tell bluebell to run the tests and tell lantern to pull dev",
                    earlier) is True, answers


def test_L12_yes_plus_an_extra_clause(daemon, answers):
    talk = [("assistant", "Claude Code wants to run rm -rf build. Yes or no?")]
    assert relevant(daemon, "Run the linter.", "yes, and then run the linter", [], talk) is True, answers


def test_L13_switch_plus_a_request_is_a_request(daemon, answers):
    assert relevant(daemon, "Run the tests.", "switch to beta and run the tests") is True, answers


def test_L13_control_switch_alone_is_not(daemon, answers):
    assert relevant(daemon, "Run the tests.", "switch to beta", ["Run the tests."]) is False, answers


@pytest.mark.parametrize("said", ["tell all sessions to pull dev", "תגיד לכל הסשנים למשוך dev"])
def test_L14_broadcast(said, daemon, answers):
    assert relevant(daemon, "Pull dev.", said) is True, answers


def test_L15_verdicts_are_stable_and_not_empty(daemon, answers):
    verdicts = [relevant(daemon, "Run the tests.", "run the tests") for _ in range(5)]
    assert verdicts == [True] * 5, answers


# idle assessment

@pytest.mark.parametrize("final,waiting", [
    ("Should I use banker's rounding or half-up for totals?", True),
    ("Done. All 12 tests pass and the branch is pushed.", False),
])
def test_L16_idle_assessment(final, waiting, daemon, answers, tmp_path):
    session = make(tmp_path, "cv-repo/main", REPO_TEXT)
    session.idle_since = time.time()
    asyncio.run(daemon._digest_turn(session, f"{CC_FINISHED} Its final message:\n{final}"))
    assert (session.needs is not None) is waiting, (session.needs, answers)
