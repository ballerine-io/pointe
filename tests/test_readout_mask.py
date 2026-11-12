"""readout.mask is the one credential rule for what is read out, alerted, shown and briefed. An unquoted value after a
secret-like name with a colon or an equals sign, spaces allowed around it, is a credential too."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import readout  # noqa: E402

SYNTHETIC = "hunter2xyz"


@pytest.mark.parametrize("text", [
    f"password: {SYNTHETIC}", f"PASSWORD:{SYNTHETIC}", f"the db Secret= {SYNTHETIC} for now", f"TOKEN : {SYNTHETIC}",
    f"api_key: {SYNTHETIC}", f"x_auth_token =  {SYNTHETIC}", f"Password => {SYNTHETIC}", f"client_secret:\t{SYNTHETIC}",
    f"retry with token: {SYNTHETIC}, then report"])
def test_an_unquoted_value_after_a_secret_name_is_masked(text):
    masked = readout.mask(text)
    assert SYNTHETIC not in masked and readout.MASK in masked
    assert readout.redact(text) is None  # never read out or put in a notification


@pytest.mark.parametrize("text", [
    "token: 5", "monkey: banana", "password reset link sent", "keys: 3 of them",
    "Run the tests and report.", "secret santa is on Friday"])
def test_plain_words_are_left_alone(text):
    assert readout.mask(text) == text and readout.redact(text) == text


def test_the_existing_forms_still_mask():
    for text in (f'password = "{SYNTHETIC}"', f"export API_KEY={SYNTHETIC}", f"curl --token {SYNTHETIC}",
                 f"https://user:{SYNTHETIC}@example.invalid/x"):
        assert SYNTHETIC not in readout.mask(text), text
