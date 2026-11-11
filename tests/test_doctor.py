"""bin/voice-doctor's advice: what a setup measured, and the one key that would improve it most."""

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
    assert doctor.advice(keys, keys)[-1] == "You have every key the best measured setup uses."


def test_every_measured_result_is_filled_in():
    assert not any("@@" in result for result, _ in doctor.MEASURED.values())
