"""pointe doctor's verdict and advice match what Pointe will do. QA round 2: "Pointe is ready" while the start refused the
Gemini key; on Free start "Next key: soniox", which the setup then did not use, shown as "another key fills its roles";
jargon about Soniox and a "mirror stream" at every Free start start-up."""

import socket
import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
import doctor  # noqa: E402
import keys  # noqa: E402
import setups  # noqa: E402
import vendors  # noqa: E402


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def free_start(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_VOICE_STATE", str(tmp_path))
    monkeypatch.setenv("CLAUDE_VOICE_DAEMON_PORT", str(_free_port()))  # nothing runs there
    setups.choose("free")
    monkeypatch.setattr(sys, "argv", ["doctor.py"])
    return tmp_path


def _keys(monkeypatch, *present):
    monkeypatch.setattr(vendors, "key", lambda v: "made-up" if v in present else None)


def test_with_pointe_stopped_a_refused_key_is_not_ready(free_start, monkeypatch, capsys):
    _keys(monkeypatch, "gemini")
    monkeypatch.delenv("CLAUDE_VOICE_SKIP_KEY_CHECK", raising=False)
    checked = []
    monkeypatch.setattr(keys, "check", lambda v: checked.append(v) or (False, "The gemini key was refused."))
    assert doctor.main() == 1
    out = capsys.readouterr().out
    assert out.startswith("Pointe is not ready: the Gemini key was refused.") and checked == ["gemini"]


def test_with_pointe_stopped_a_key_that_works_or_cannot_be_checked_is_ready(free_start, monkeypatch, capsys):
    _keys(monkeypatch, "gemini")
    monkeypatch.delenv("CLAUDE_VOICE_SKIP_KEY_CHECK", raising=False)
    monkeypatch.setattr(keys, "check", lambda v: (None, "offline"))
    assert doctor.main() == 0 and capsys.readouterr().out.startswith("Pointe is ready.")


def test_on_free_start_the_advice_names_the_setup_that_uses_the_next_key(free_start, monkeypatch, capsys):
    _keys(monkeypatch, "gemini", "soniox")
    doctor.main()
    out = capsys.readouterr().out
    assert "Next key:" not in out
    assert "found    soniox (not used: the Free start setup does not use it)" in out
    assert "pointe setup full" in out and "Anthropic and the ElevenLabs keys" in out


def test_with_no_setup_chosen_the_next_key_advice_is_unchanged():
    assert doctor.advice({"gemini"}, {"gemini"})[1].startswith("Next key: soniox.")


def test_free_start_says_use_headphones_in_plain_words(free_start, monkeypatch, capsys):
    _keys(monkeypatch, "gemini")
    doctor.main()
    out = capsys.readouterr().out
    assert "Use headphones: on speakers Pointe can hear itself." in out and "mirror stream" not in out
    assert "mirror stream" not in " ".join(vendors.resolve("brain").notes)


def test_a_running_call_that_lost_its_ears_is_not_ready():
    status = {"needed": [], "fix": None}
    line = doctor.verdict(0, status, None, [], [("lost", "gemini")])[0]
    assert line.startswith("Pointe is not ready") and "Gemini" in line and "reconnecting" in line
