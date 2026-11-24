"""A short report of work the user asked for is said in Claude's own words, without waiting for the reader.

From the first tester round: a finished session was reported a median 3.7 s after it stopped (p90 7.0 s, worst
13.7 s): every report waited for the reader's pass, even "Docstring added to load_batches. No tests were run." When the
user sent that session the work and its final message is short and plain, it is said as it came (with the session's
name when several are on the call), and the reader's pass still runs in the background for the notes and what the
session waits on.

uv run pytest -q tests/test_quick_report.py
"""

import asyncio
import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import add, d, fake_conn  # noqa: E402,F401  (d is the daemon fixture)


def _finished(d, text):  # noqa: F811
    return f"[claude-code {d.FINISHED_MARK} {d.FINAL_MARK}{text}"


def test_a_short_report_of_work_the_user_sent_is_said_as_it_came(d, monkeypatch):  # noqa: F811
    s = add(d, "g", "granary")
    add(d, "l", "ledgerline")
    d.REGISTRY.mode = "orchestrator"
    d.state.conn = fake_conn()
    d.state.unconfirmed["g"] = ["Add a docstring to load_batches."]
    digested = []

    async def digest(session, text):
        digested.append(1)
        return {}
    monkeypatch.setattr(d, "_digest_turn", digest)
    asyncio.run(d.feed(s, _finished(d, "Docstring added to `load_batches`. No tests were run."), True))
    fed = d.state.conn.injector.fed
    assert fed and fed[-1][1] is True
    assert d._VERBATIM[fed[-1][0]] == "granary: Docstring added to load batches. No tests were run."


def test_a_report_nobody_asked_for_or_a_long_one_goes_through_the_reader(d, monkeypatch):  # noqa: F811
    s = add(d, "g", "granary")
    d.state.conn = fake_conn()

    async def digest(session, text):
        return {"speak": False, "final": text, "excerpt": text}
    monkeypatch.setattr(d, "_digest_turn", digest)
    asyncio.run(d.feed(s, _finished(d, "Docstring added."), True))  # the user sent it nothing
    assert not any(t in d._VERBATIM for t, _ in d.state.conn.injector.fed)
