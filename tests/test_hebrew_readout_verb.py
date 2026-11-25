"""A permission request read out in Hebrew says its verb in Hebrew: "billing מבקש להריץ: ls", not "מבקש: run: ls".

From the first tester round (heb-03): "בילינג מבקש. run. ls, then python 3, pytest tests. לבצע?" The command itself
stays exactly as it runs; only the read-out's own word for what it does is translated.

uv run pytest -q tests/test_hebrew_readout_verb.py
"""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import d  # noqa: E402,F401  (d is the daemon fixture)


@pytest.mark.parametrize("spoken,said", [
    ("run: python3 unittest", "להריץ: python3 unittest"),
    ("edit refunds.py", "לערוך את refunds.py"),
    ("write notes.txt", "לכתוב את notes.txt"),
    ("read README.md", "לקרוא את README.md"),
    ("run, word for word: for f in *; do wc $f; done", "להריץ, מילה במילה: for f in *; do wc $f; done"),
    ("use WebFetch, word for word: url: https://example.org", "להשתמש ב-WebFetch, מילה במילה: url: https://example.org"),
])
def test_the_verb_is_hebrew_and_the_command_is_exact(d, spoken, said):  # noqa: F811
    assert d._hebrew_request(spoken) == said


@pytest.mark.parametrize("spoken,said", [
    # heb-03 in tester round 4's first sample: "LS Scripts App Tests, then Head Test… then Python 3 Unit Taste Discover"
    ("run: ls scripts then head test_refunds.py then python3 unittest discover",
     "להריץ: ls scripts ואז head test_refunds.py ואז python3 unittest discover"),
    ("run: python3 pytest tests writing to out.txt", "להריץ: python3 pytest tests וכותב ל-out.txt"),
])
def test_the_joining_words_of_a_short_read_out_are_hebrew_too(d, spoken, said):  # noqa: F811
    assert d._hebrew_request(spoken) == said
