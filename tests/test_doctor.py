"""bin/voice-doctor's advice: what a setup measured, and the one key that would improve it most."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import doctor  # noqa: E402


def test_no_key_starts_with_gemini():
    assert doctor.advice(set(), set())[0].startswith("Start with one Gemini key")


def test_a_setup_that_cannot_run_names_the_missing_half():
    assert "Anthropic" in doctor.advice({"soniox"}, set())[0]
    assert "Soniox" in doctor.advice({"anthropic"}, set())[0]


def test_one_key_reports_its_measured_result_and_the_biggest_next_step():
    lines = doctor.advice({"gemini"}, {"gemini"})
    assert lines[0].startswith("This setup: ") and "not run" not in lines[0]
    assert lines[1].startswith("Next key: soniox.")


def test_next_key_skips_what_is_present():
    assert doctor.advice({"anthropic", "soniox"}, {"anthropic", "soniox"})[1].startswith("Next key: elevenlabs.")


def test_an_unmeasured_mix_says_so():
    assert doctor.advice({"anthropic", "openai"}, {"anthropic", "openai"})[0] == "This setup: not run through the audio suite yet."


def test_the_best_setup_has_nothing_to_add():
    keys = {"anthropic", "soniox", "gemini", "elevenlabs"}
    assert doctor.advice(keys, keys)[-1] == "You have every key of the fastest and most accurate voice setup."


def test_every_measured_result_is_filled_in():
    assert not any("@@" in result for result, _ in doctor.MEASURED.values())


def test_setup_reads_back_the_doctors_verdict_whatever_the_wrapper_prints_first():
    """bin/voice-doctor prints "ok uv" and the node line before doctor.py's verdict, so "its first line" is always
    "ok uv". /pointe:setup names the verdict by the words every verdict starts with."""
    root = Path(__file__).resolve().parents[1]
    wrapper = (root / "bin" / "voice-doctor").read_text()
    assert 'echo "ok       uv"' in wrapper, "the wrapper's own lines come first"
    text = " ".join((root / "plugin" / "commands" / "setup.md").read_text().split())
    assert "first line back" not in text
    said = re.search(r'Read back only its verdict: the line that starts ((?:"[^"]+"(?: or )?)+)', text).group(1)
    prefixes = tuple(re.findall(r'"([^"]+)"', said))
    ready, needs = {"needed": False, "fix": None}, {"needed": True, "fix": "gemini"}
    for lines in (doctor.verdict(0, ready, None, []), doctor.verdict(0, ready, None, ["gemini"]),
                  doctor.verdict(0, needs, None, []), doctor.verdict(1, {"needed": True, "fix": None}, None, [])):
        assert lines[0].startswith(prefixes), (lines[0], prefixes)
