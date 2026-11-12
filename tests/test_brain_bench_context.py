"""The brain benchmark must send the brain what the daemon sends: its context comes from daemon._brain_context, seeded
with each case. Offline: no model is called."""

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent.parent / "bench")]

import brain_bench  # noqa: E402
import brain_cases as bc  # noqa: E402
import daemon  # noqa: E402


def test_bench_context_is_the_daemons_and_carries_every_case_fact():
    for case in bc.BRAIN_CASES:
        block, needs = brain_bench.daemon_context(case)
        assert block == daemon._brain_context(), case.name
        assert block.endswith(needs), case.name
        assert f"Routing mode: {case.mode}." in block, case.name
        for s in case.sessions:
            for fact in [s.name, *s.waits, *s.clocks, *s.sent] + ([s.typed] if s.typed else []):
                assert fact in needs, f"{case.name}: {fact!r} missing from the daemon's needs list"
            if s.notes and s.notes.get("state"):
                assert s.notes["state"] in needs, case.name


def test_bench_has_no_copy_of_the_context_format():
    for copy in ("right_now", "needs_block"):
        assert not hasattr(bc, copy), f"brain_cases.{copy} is a hand copy of the daemon's context; derive it instead"
