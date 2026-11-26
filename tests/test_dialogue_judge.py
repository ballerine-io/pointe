"""The naturalness judge is named and priced by the model that judged.

Tester round 6: with only DLG_JUDGE_MODEL=claude-opus-5-5 set, `run.py judge` asked Opus but wrote
judge-pointe.claude-fable-5-1.json and priced the calls at Fable's rates, because `--judge` defaulted to Fable while the
Anthropic call used the environment's model. No keys, no models.
"""

import json
from types import SimpleNamespace

import conv_suite

CONV_SUITE = "dialogues"
conv_suite.enter(CONV_SUITE)

import run as dlg_run  # noqa: E402
from core import ledger  # noqa: E402
from dialogues import judge  # noqa: E402


def _judging(tmp_path, monkeypatch, env_model: str):
    asked, priced = [], []

    class Messages:
        def create(self, model, **_):
            asked.append(model)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text='{"score": 4}')],
                                   usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0,
                                                         cache_creation_input_tokens=0))

    monkeypatch.setattr("anthropic.Anthropic", lambda *a, **k: SimpleNamespace(messages=Messages()))
    monkeypatch.setattr(dlg_run, "key", lambda *a: "not-a-key")
    monkeypatch.setattr(dlg_run, "load_rows", lambda ids: [{"dialogue": "t-01", "arm": "pointe"}])
    monkeypatch.setattr(judge, "transcript", lambda row: "a transcript")
    monkeypatch.setattr(ledger, "token_cost", lambda model, usage: priced.append(model) or 0.0)
    monkeypatch.setattr(ledger, "append", lambda record: None)
    monkeypatch.setattr(judge, "HERE", tmp_path)
    monkeypatch.setattr(judge, "MODEL", env_model)  # DLG_JUDGE_MODEL, read at import
    (tmp_path / "results" / "r1").mkdir(parents=True)
    return asked, priced, tmp_path / "results" / "r1"


def test_the_environments_judge_is_the_one_asked_named_and_priced(tmp_path, monkeypatch):
    asked, priced, out = _judging(tmp_path, monkeypatch, "claude-opus-5-5")
    judge.main(["r1"], "pointe", None)  # run.py with no --judge
    assert asked == priced == ["claude-opus-5-5"]
    assert json.loads((out / "judge-pointe.json").read_text())["model"] == "claude-opus-5-5"
    assert not list(out.glob("judge-pointe.claude-*.json"))


def test_a_judge_named_on_the_command_line_is_the_one_asked_named_and_priced(tmp_path, monkeypatch):
    asked, priced, out = _judging(tmp_path, monkeypatch, "claude-opus-5-5")
    judge.main(["r1"], "pointe", "anthropic:claude-fable-5-1")
    assert asked == priced == ["claude-fable-5-1"]
    assert json.loads((out / "judge-pointe.claude-fable-5-1.json").read_text())["model"] == "claude-fable-5-1"
