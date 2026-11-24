"""A Hebrew yes or no that the ears wrote in Latin letters still answers. QA round 2: on Free start a spoken "כן" came back
as "Ken" (twice), consent() did not take it, and the approval never landed."""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
from guards import consent, permission_answer  # noqa: E402


@pytest.mark.parametrize("heard", ["Ken", "Ken.", "ken, ken!"])
def test_ken_alone_is_yes(heard):
    assert consent(heard) == "allow" and permission_answer(heard) == "allow"


@pytest.mark.parametrize("heard", ["Lo.", "lo lo"])
def test_lo_alone_is_no(heard):
    assert consent(heard) == "deny" and permission_answer(heard) == "deny"


@pytest.mark.parametrize("heard", ["Ken?", "Ken said it is fine", "Ask Ken.", "Lo and behold"])
def test_the_name_or_a_question_is_no_answer(heard):
    assert permission_answer(heard) != "allow"
