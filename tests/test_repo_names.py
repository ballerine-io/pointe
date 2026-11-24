"""A spoken code name reaches the session as the name its code really has: "loadBatches" is load_batches.

From the first tester round: load_batches arrived as "loadBatches", calc_total as "calcTotal", dedupe_rows as
"dedupeRows" (the recognizer writes names it hears as camel case), and the session then said "there's no loadBatches,
so I assumed load batches", or created a file named after the wrong spelling. A name in the message that matches exactly
one name in the session's own code, case, underscores and spaces aside, is written as the code has it. A name the code
does not have is left as said: it may be a new one the user asked for.

uv run pytest -q tests/test_repo_names.py
"""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import relay  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from test_orchestrator import d  # noqa: E402,F401  (d is the daemon fixture)


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "pipeline").mkdir()
    (tmp_path / "pipeline" / "load.py").write_text("def load_batches(path):\n    pass\n\n\ndef dedupe_rows(rows):\n    pass\n")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "refunds.py").write_text("def calc_total(items):\n    pass\n\nclass RefundPolicy:\n    pass\n")
    return tmp_path


@pytest.mark.parametrize("message,fixed", [
    ("Add a docstring to loadBatches.", "Add a docstring to load_batches."),
    ("Rename calcTotal to compute_invoice_total.", "Rename calc_total to compute_invoice_total."),
    ("Add a docstring to the function dedupe rows.", "Add a docstring to the function dedupe_rows."),
    ("Make refund_policy configurable.", "Make RefundPolicy configurable."),
    ("Add a docstring to dedupe rows explaining that it keeps the first copy.",
     "Add a docstring to dedupe_rows explaining that it keeps the first copy."),
    ("Add logging to load batches that prints the batch number.",
     "Add logging to load_batches that prints the batch number."),
])
def test_a_name_the_code_has_is_written_as_the_code_has_it(repo, message, fixed):
    assert relay.repo_names(message, relay.code_names(str(repo))) == fixed


@pytest.mark.parametrize("message", ["Add logging to the loader.", "Rename it to computeInvoiceTotal.",
                                     "Load batches faster, please."])
def test_anything_else_is_left_as_said(repo, message):
    assert relay.repo_names(message, relay.code_names(str(repo))) == message


def test_the_send_writes_the_codes_name(d, tmp_path, monkeypatch):  # noqa: F811
    import asyncio

    from test_orchestrator import add, open_gates, record_dispatch

    (tmp_path / "load.py").write_text("def load_batches(path):\n    pass\n")
    add(d, "g", "granary", cwd=str(tmp_path))
    sent = record_dispatch(d, monkeypatch)
    open_gates(d, monkeypatch, "Tell granary to add a docstring to load batches.")
    d.state.brain_target = "granary"
    asyncio.run(d._send("Add a docstring to loadBatches."))
    assert sent and "load_batches" in sent[0][1] and "loadBatches" not in sent[0][1]
