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
        for i, s in enumerate(case.sessions):
            facts = [s.name, *s.waits, *s.clocks, *s.sent] + ([s.typed] if s.typed else [])
            if case.mode == "session" and i != case.active:  # session mode: the brain hears of the session in focus only
                assert not [f for f in facts if f in needs], f"{case.name}: another session's state reached the brain"
                continue
            for fact in facts:
                assert fact in needs, f"{case.name}: {fact!r} missing from the daemon's needs list"
            if s.notes and s.notes.get("state"):
                assert s.notes["state"] in needs, case.name


def test_bench_has_no_copy_of_the_context_format():
    for copy in ("right_now", "needs_block"):
        assert not hasattr(bc, copy), f"brain_cases.{copy} is a hand copy of the daemon's context; derive it instead"


def test_bench_send_stub_applies_the_daemons_typed_approval_refusal():
    case = next(c for c in bc.BRAIN_CASES if c.name == "typed_merge")
    refused = brain_bench.sent_refusal(case, {"message": "The owner approves: merge the outbox branch."})
    assert refused and "type it in the terminal" in refused["error"]
    assert brain_bench.sent_refusal(case, {"message": "What is still failing?"}) is None


def test_only_a_read_only_lookup_is_excused_and_only_before_the_challenge():
    assert bc.lookup_only("Please find the peak traffic for the old page. We plan to launch Friday.")
    assert not bc.lookup_only("Put the retries back on Redis.")
    assert not bc.lookup_only("Find the failing test and fix it.")
    before = next(c for c in bc.BRAIN_CASES if c.name == "chl_no_evidence_before")
    after = next(c for c in bc.BRAIN_CASES if c.name == "chl_no_evidence_after")
    assert before.rubric.lookup_ok and not after.rubric.lookup_ok
