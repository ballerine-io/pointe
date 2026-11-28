"""A new name the user said reaches the session in the style they said, or in the style of the code.

From HLK at 0.8.5 (bench/conversational/hlk/results/hlk-20261125-170854): the recognizer writes a name it hears in camel
case, and glues a style said after it into the name. "Call it bin report, snake case" reached the session as
binReportSnakeCase, and the session made a function of that name (long-dictation, 5 of 6 runs, 2 of them also invalid);
"rename get rate to fetch rate" became "rename get_rate to fetchRate", the code's name fixed by repo_names and the new one
left in camel case beside it, and the session followed it word for word (self-correction-1, 2 of 3; mid-task-redirect-1,
computeTax, 1 of 3). The keyboard and the router passed every one of these runs. A style the user said wins; with none,
a new name follows the code when every name it defines is snake case. A name the code has is left alone (repo_names).

uv run --locked --group test-tools pytest -q tests/test_spoken_name_style.py
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import relay  # noqa: E402
from test_orchestrator import add, d, open_gates, record_dispatch  # noqa: E402,F401  (d is a fixture)


@pytest.fixture
def snake(tmp_path):
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "fees.py").write_text("def get_rate(amount):\n    return round(amount * 0.03, 2)\n")
    (tmp_path / "api" / "routes.py").write_text("from api.fees import get_rate\n\n\ndef checkout(amount):\n"
                                                "    return amount + get_rate(amount)\n")
    return relay.code_names(str(tmp_path))


@pytest.fixture
def twins(tmp_path):
    (tmp_path / "retry.py").write_text("def parse_retry_after(value):\n    return int(value)\n")
    (tmp_path / "compat.py").write_text("def parseRetryAfter(value):\n    return int(value)\n")
    return relay.code_names(str(tmp_path))


@pytest.mark.parametrize("message,said,fixed", [
    ("In crate.py, add a new function named binReportSnakeCase. It takes a list of numbers.",
     "Okay, so, um, in crate dot py I need a new function, uh, call it binReportSnakeCase, that takes a list of numbers.",
     "In crate.py, add a new function named bin_report. It takes a list of numbers."),
    ("In rack.py, add a new function named loadOverviewSnakeCase (name as the user said it).",
     "in rack dot py I need a new function, uh, call it load overview, snake case, that takes a list",
     "In rack.py, add a new function named load_overview (name as the user said it)."),
    ("In crate.py, add a function binReport that returns a dictionary.",
     "in crate dot py add a function, call it bin report, snake case, that returns a dictionary",
     "In crate.py, add a function bin_report that returns a dictionary."),
    ("Add a helper loadOverviewCamelCase to rack.js.", "add a helper load overview, camel case, to rack dot js",
     "Add a helper loadOverview to rack.js."),
])
def test_a_style_the_user_said_is_the_names_style(message, said, fixed):
    assert relay.spoken_style(message, said, {}) == fixed


def test_a_new_name_follows_code_that_is_all_snake_case(snake):
    message = "Rename the function get_rate to fetchRate (final name; the user first said fetchRatio). Only in api."
    said = "Rename getRate to fetchRatio, no wait, to fetchRate, and only in the api package."
    assert relay.spoken_style(message, said, snake) == \
        "Rename the function get_rate to fetch_rate (final name; the user first said fetch_ratio). Only in api."


@pytest.mark.parametrize("message,said", [
    ("Rename get_rate to fetchRate.", "rename get rate to fetch rate, camel case"),  # the user said camel case
    ("Rename it to computeInvoiceTotal.", "rename it to computeInvoiceTotal"),  # no code to follow, no style said
])
def test_a_new_name_stays_when_the_user_said_camel_case_or_the_code_says_nothing(snake, message, said):
    assert relay.spoken_style(message, said, snake if "get_rate" in message else {}) == message


def test_code_with_camel_case_names_sets_no_style_and_its_own_names_stay(twins):
    message = "Fix parse_retry_after, not parseRetryAfter, and add retryAfterMs beside it."
    assert relay.spoken_style(message, "fix parse retry after, not parseRetryAfter, and add retryAfterMs", twins) == message


def test_the_send_writes_a_new_name_in_the_codes_style(d, tmp_path, monkeypatch):  # noqa: F811
    (tmp_path / "utils.py").write_text("def calc_tax(x):\n    return round(x * 0.2, 2)\n")
    (tmp_path / "invoice.py").write_text("from utils import calc_tax\n\n\ndef show(x):\n    return str(calc_tax(x))\n")
    add(d, "t", "fennel", cwd=str(tmp_path))
    sent = record_dispatch(d, monkeypatch)
    open_gates(d, monkeypatch, "Rename calcTax to computeTax everywhere in this repo, in every file that uses it.")
    d.state.brain_target = "fennel"
    asyncio.run(d._send("Rename the function calc_tax to computeTax everywhere in this repo."))
    assert sent and "compute_tax" in sent[0][1] and "computeTax" not in sent[0][1].split("\n\n(Said by voice")[0]
