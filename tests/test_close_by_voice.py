"""Closing and renaming sessions by voice: which sessions the user's own words pick, and when the voice may act.

Closing takes a session off the voice; it keeps running in its terminal. One session the user clearly named goes at
once. Several, or "all except ...", are read back once and go on the user's yes, never on the model's say-so.

uv run --locked pytest -q tests/test_close_by_voice.py
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from guards import close_request, disconnect_intent  # noqa: E402
from sessions import Session  # noqa: E402
from test_orchestrator import (Params, _consent_setup, add, d, fake_conn, model_says, verdicts,  # noqa: E402,F401
                               with_permission)

KEEP = ["harbor-research", "voice-addon", "kestrel-sandbox"]
CLOSE = ["orchard-bank", "atlas-feature", "pelican-discovery-tool", "browser-access-question"]
# The shape of a sentence from a real call, with invented names: every close was refused, four times over.
ALL_BUT_THREE = "Close all the session besides harbor, voice, and kestrel."


def _sessions(names):
    return [Session(id=n, name=n, cwd="/tmp", pid=1, transcript="/tmp/none.jsonl") for n in names]


def _names(found):
    return sorted(s.name for s in found)


# ---------- what counts as asking ----------

@pytest.mark.parametrize("said", [
    "Close atlas.", "close the atlas session", "disconnect atlas", "drop the atlas session", "remove atlas from the voice",
    "take atlas off the voice", "take atlas and orchard off", "hang up on atlas", "kick atlas", "atlas can leave",
    "let atlas leave the call", "close these sessions", "close the rest", "סגור את atlas", "תסגור את atlas",
    "תנתק את atlas", "תוריד את atlas", "תסגרי את כל הסשנים", "תוציא את atlas מהשיחה"])
def test_close_words_in_english_and_hebrew_ask_to_take_a_session_off(said):
    assert disconnect_intent(said), said


@pytest.mark.parametrize("said", [
    "Tell atlas to close the pull request.", "Ask orchard to remove the old README.", "What is atlas doing?",
    "תגיד ל atlas לסגור את הבאג", "rename atlas to pricing"])
def test_a_task_that_closes_something_is_not_a_close(said):
    assert not disconnect_intent(said), said


# ---------- which sessions the words pick ----------

def test_all_except_three_picks_the_other_four():
    sessions = _sessions(KEEP + CLOSE)
    ask = close_request(ALL_BUT_THREE, sessions)
    assert ask is not None and ask.inverse and not ask.ties and not ask.unclear
    assert _names(ask.close) == sorted(CLOSE) and _names(ask.keep) == sorted(KEEP)


@pytest.mark.parametrize("said", [
    "close everything except harbor, voice and kestrel",
    "disconnect all sessions but harbor, voice and kestrel",
    "close all of them other than harbor, voice, kestrel",
    "keep harbor, voice and kestrel, close the rest",
    "harbor, voice and kestrel stay. Close everything else.",
    "close the others, keep harbor voice and kestrel",
    "תסגור את כל הסשנים חוץ מ-harbor, voice ו-kestrel",
    "סגור הכל מלבד harbor, voice ו kestrel",
    "תשאיר את harbor, voice ו-kestrel ותסגור את השאר",
])
def test_inverse_selection_in_its_usual_wordings(said):
    sessions = _sessions(KEEP + CLOSE)
    ask = close_request(said, sessions)
    assert ask is not None and ask.inverse and not ask.ties and not ask.unclear, (said, ask)
    assert _names(ask.close) == sorted(CLOSE), said


def test_close_the_rest_with_nothing_kept_asks_which_to_keep():
    ask = close_request("close the rest", _sessions(KEEP + CLOSE))
    assert ask is not None and ask.unclear and not ask.close


@pytest.mark.parametrize("said", ["close orchard and atlas", "close orchard, and the atlas session",
                                  "take orchard and atlas off the voice", "תסגור את orchard ואת atlas"])
def test_several_named_sessions(said):
    ask = close_request(said, _sessions(KEEP + CLOSE))
    assert ask is not None and not ask.inverse and _names(ask.close) == ["atlas-feature", "orchard-bank"], (said, ask)


def test_a_name_two_sessions_answer_to_is_a_tie():
    sessions = _sessions(["alpha/main", "alpha/dev", "beta/main"])
    ask = close_request("close alpha", sessions)
    assert ask is not None and [_names(t) for t in ask.ties] == [["alpha/dev", "alpha/main"]] and not ask.close
    keep_tie = close_request("close everything except alpha", sessions)
    assert keep_tie is not None and [_names(t) for t in keep_tie.ties] == [["alpha/dev", "alpha/main"]]


def test_the_voice_the_session_leaves_is_not_a_session_named():
    ask = close_request("remove atlas from the voice", _sessions(KEEP + CLOSE))
    assert _names(ask.close) == ["atlas-feature"]


def test_closing_a_thing_inside_a_session_names_no_session():
    ask = close_request("close the issue in atlas", _sessions(KEEP + CLOSE))
    assert ask is None or (not ask.close and ask.unclear)


# ---------- what the voice may do with it ----------

def _setup(d, names=KEEP + CLOSE):
    for n in names:
        add(d, n, n)
    d.REGISTRY.set_active(names[0])


async def _close(d, said: str | None, name: str = "atlas-feature", heard_own_words: bool = False,
                 spoken: bool = True) -> dict:
    """The user said `said` (None: nothing new since the last call), then the model called disconnect_session."""
    if said is not None:
        await d.on_user_utterance(said)
        d.state.heard_own_words = heard_own_words
    p = Params(name=name)
    await d.disconnect_session(p)
    if spoken and "confirm_first" in p.results[0]:
        await model_says(d)  # the read-back is said, as the model's reply would say it on a call
    return p.results[0]


def test_one_clearly_named_session_closes_at_once_and_keeps_running(d, monkeypatch):
    _setup(d)
    killed = []
    monkeypatch.setattr(os, "kill", lambda *a: killed.append(a))
    result = asyncio.run(_close(d, "close atlas"))
    assert result["disconnected"] == "atlas-feature" and "terminal" in result["note"], result
    assert "atlas-feature" not in d.REGISTRY.sessions and len(d.REGISTRY.sessions) == 6
    assert killed == []  # off the voice only: nothing signals its process


def test_all_except_three_is_read_back_then_closed_on_yes(d):
    _setup(d)

    async def scenario():
        first = await _close(d, ALL_BUT_THREE, name="orchard-bank")
        repeats = [await _close(d, None, name=n) for n in CLOSE[1:]]  # the model called once per session, as it did live
        still = set(d.REGISTRY.sessions)
        done = await _close(d, "Yes.", name="orchard-bank")
        return first, repeats, still, done

    first, repeats, still, done = asyncio.run(scenario())
    say = first["confirm_first"]
    assert say.startswith("Closing ") and say.endswith("Close them?"), say
    closing, keeping = say.split("Keeping")
    assert all(n in closing for n in CLOSE) and all(n in keeping for n in KEEP), say
    assert all("error" in r for r in repeats) and still == set(KEEP + CLOSE)  # nothing closed before the yes
    assert sorted(done["disconnected"]) == sorted(CLOSE) and set(d.REGISTRY.sessions) == set(KEEP), done


def test_hebrew_all_except_and_a_hebrew_yes(d):
    _setup(d)

    async def scenario():
        first = await _close(d, "תסגור את כל הסשנים חוץ מ-harbor, voice ו-kestrel")
        return first, await _close(d, "כן")

    first, done = asyncio.run(scenario())
    assert "confirm_first" in first and sorted(done["disconnected"]) == sorted(CLOSE), (first, done)


def test_several_named_sessions_are_read_back_too(d):
    _setup(d)

    async def scenario():
        return await _close(d, "close orchard and atlas"), await _close(d, "go ahead")

    first, done = asyncio.run(scenario())
    assert "confirm_first" in first and sorted(done["disconnected"]) == ["atlas-feature", "orchard-bank"]


@pytest.mark.parametrize("answer", ["no", "wait, not atlas", "what is pelican doing?"])
def test_anything_but_a_plain_yes_closes_nothing(d, answer):
    _setup(d)

    async def scenario():
        await _close(d, ALL_BUT_THREE)
        return await _close(d, answer)

    result = asyncio.run(scenario())
    assert "error" in result and set(d.REGISTRY.sessions) == set(KEEP + CLOSE), result


def test_the_read_back_heard_back_is_not_a_yes(d):
    _setup(d)

    async def scenario():
        await _close(d, ALL_BUT_THREE)
        return await _close(d, "go ahead", heard_own_words=True)

    result = asyncio.run(scenario())
    assert "error" in result and set(d.REGISTRY.sessions) == set(KEEP + CLOSE)


def test_a_yes_long_after_the_read_back_closes_nothing(d, monkeypatch):
    _setup(d)

    async def scenario():
        await _close(d, ALL_BUT_THREE)
        d.state.pending_close = (d.state.pending_close[0] - d.CLOSE_CONFIRM_SECS - 1, *d.state.pending_close[1:])
        return await _close(d, "yes")

    result = asyncio.run(scenario())
    assert "error" in result and set(d.REGISTRY.sessions) == set(KEEP + CLOSE)


def test_an_ambiguous_close_asks_which_and_closes_nothing(d):
    _setup(d, ["alpha/main", "alpha/dev", "beta/main"])
    result = asyncio.run(_close(d, "close alpha", name="alpha/main"))
    assert "error" in result and "alpha/main" in result["error"] and "alpha/dev" in result["error"], result
    assert len(d.REGISTRY.sessions) == 3


@pytest.mark.parametrize("said", ["What is atlas doing?", "Tell atlas to close the pull request.", "yes"])
def test_the_voice_closes_nothing_the_user_did_not_ask_to_close(d, said):
    _setup(d)
    result = asyncio.run(_close(d, said))
    assert "error" in result and len(d.REGISTRY.sessions) == 7, result


def test_no_new_words_no_close(d, monkeypatch):
    _setup(d)
    d.state.last_utterance, d.state.last_user_speech_at = "close atlas", time.time() - 60
    d.state.last_close_at = time.time() - 30  # that request was handled already
    result = asyncio.run(_close(d, None))
    assert "error" in result and len(d.REGISTRY.sessions) == 7


def test_the_yes_to_a_read_back_never_approves_a_waiting_prompt(d, monkeypatch):
    active, posts = _consent_setup(d, monkeypatch)
    add(d, "g", "orchard-bank"), add(d, "h", "atlas-feature")

    async def scenario():
        await _close(d, "close orchard and atlas")
        d.state.conn.injector.bot_started_at = time.time()  # the read-back is spoken
        await _close(d, "yes")

    asyncio.run(scenario())
    assert verdicts(posts) == [] and active.permission_id == "p1"
    assert "g" not in d.REGISTRY.sessions and "h" not in d.REGISTRY.sessions


# ---------- rename by voice ----------

async def _rename(d, said: str, new_name: str) -> dict:
    await d.on_user_utterance(said)
    p = Params(new_name=new_name)
    await d.rename_session(p)
    return p.results[0]


@pytest.mark.parametrize("said", ["call this session pricing", "תקרא לסשן הזה pricing", "name this one pricing"])
def test_call_this_session_renames_the_active_one(d, said):
    _setup(d, ["atlas-feature", "orchard-bank"])
    result = asyncio.run(_rename(d, said, "pricing"))
    assert result == {"renamed": "atlas-feature", "to": "pricing"}, result


@pytest.mark.parametrize("said", ["rename orchard to pricing", "תשנה את השם של orchard ל pricing"])
def test_rename_a_named_session_persists_like_a_rename_from_the_page(d, said):
    _setup(d, ["atlas-feature", "orchard-bank"])
    result = asyncio.run(_rename(d, said, "pricing"))
    assert result == {"renamed": "orchard-bank", "to": "pricing"}, result
    saved = json.loads(d.REGISTRY.path.read_text())
    assert "pricing" in json.dumps(saved) and d.REGISTRY.sessions["orchard-bank"].named_by == "user"


def test_no_rename_the_user_did_not_ask_for(d):
    _setup(d, ["atlas-feature", "orchard-bank"])
    result = asyncio.run(_rename(d, "pricing looks good", "pricing"))
    assert "error" in result and d.REGISTRY.sessions["atlas-feature"].name == "atlas-feature"


def test_no_rename_to_a_name_the_user_did_not_say(d):
    _setup(d, ["atlas-feature", "orchard-bank"])
    result = asyncio.run(_rename(d, "rename orchard to pricing", "billing"))
    assert "error" in result and d.REGISTRY.sessions["orchard-bank"].name == "orchard-bank"


def test_the_read_back_is_said_word_for_word_whatever_the_model_writes(d):
    """From live runs: the model said "Closing shop-tests. Keeping billing and shop." and dropped its question, twice out
    of two, so the user heard no question. The read-back is the daemon's: it goes out exactly, and only once."""
    from types import SimpleNamespace

    _setup(d)
    first = asyncio.run(_close(d, ALL_BUT_THREE, name="orchard-bank", spoken=False))
    line = first["confirm_first"]
    spoken = []

    async def push(frame):
        spoken.append(frame.text)

    front = SimpleNamespace(push_frame=push)
    assert not d.BrainFront._may_speak_early_now()  # the reply arrives whole, so it can be checked before it is said
    asyncio.run(d.BrainFront._speak(front, "Closing orchard-bank, atlas-feature and two more. Keeping the rest."))
    asyncio.run(d.BrainFront._speak(front, "Anything else?"))
    assert spoken[0] == d._spoken_names(line) and spoken[1] == "Anything else?"


# ---------- the yes to a read-back keeps a permission prompt's rules (Mythos review AV-3, AV-5) ----------

def test_a_yes_with_a_condition_closes_nothing(d):
    _setup(d)

    async def scenario():
        await _close(d, ALL_BUT_THREE)
        return await _close(d, "okay, except the last one")

    result = asyncio.run(scenario())
    assert "error" in result and set(d.REGISTRY.sessions) == set(KEEP + CLOSE), result


def test_a_typed_yes_closes_nothing(d):
    from test_orchestrator import client_for
    _setup(d)
    d.state.conn = fake_conn()

    async def push(frame, direction=None):
        pass

    d.state.conn.injector.push_frame = push
    asyncio.run(_close(d, ALL_BUT_THREE))
    assert client_for(d).post("/voice/say", json={"text": "yes"}).status_code == 200
    p = Params(name="orchard-bank")
    asyncio.run(d.disconnect_session(p))
    assert "error" in p.results[0] and set(d.REGISTRY.sessions) == set(KEEP + CLOSE), p.results
