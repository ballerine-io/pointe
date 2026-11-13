"""A refused brain key is said aloud once per call, by the mouth that still works. From a live run: the user asked,
heard nothing useful, and only the page said why."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import vendors  # noqa: E402
from test_orchestrator import _brain, d  # noqa: E402,F401


class AuthenticationError(Exception):
    pass


def _refusing(monkeypatch):
    async def step(*_a):
        raise AuthenticationError("Error code: 401 - {'type': 'error', 'error': {'type': 'authentication_error', "
                                  "'message': 'invalid x-api-key'}}")

    monkeypatch.setattr(vendors, "step", step)


def test_a_refused_brain_key_is_said_once_per_call(monkeypatch):
    _refusing(monkeypatch)
    b, spoken = _brain([])
    asyncio.run(b.turn("what is lantern doing"))
    asyncio.run(b.turn("hello?"))
    assert len(spoken) == 1
    assert "gemini key was refused" in spoken[0] and "pointe key gemini" in spoken[0]


def test_the_line_is_silent_when_the_mouth_uses_the_refused_key(d, monkeypatch):
    monkeypatch.setattr(d, "_setup", vendors.Setup(brain="gemini:b", mouth="gemini:tts"))
    assert d._key_refused_line("gemini") is None


def test_the_line_follows_the_users_language(d, monkeypatch):
    monkeypatch.setattr(d.state, "last_utterance", "מה קורה עם הסשן")
    he = d._key_refused_line("gemini")
    monkeypatch.setattr(d.state, "last_utterance", "what is going on")
    en = d._key_refused_line("gemini")
    assert "pointe key gemini" in he and any("֐" <= c <= "׿" for c in he)
    assert en.startswith("My gemini key was refused")


def test_the_daemon_brain_uses_the_daemon_line(d, monkeypatch):
    _refusing(monkeypatch)
    monkeypatch.setattr(d, "_setup", vendors.Setup(brain="anthropic:b", mouth="anthropic:x"))
    spoken = []

    async def speak(text, request_id=None):
        spoken.append(text)

    b = d.make_brain(speak)
    asyncio.run(b.turn("hello"))
    assert spoken == []
