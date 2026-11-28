"""A committed file against what its generator writes now.

`assert committed == made, "run: ..."` on a stale file made pytest diff the two whole texts character by character:
on the benchmark pages that took longer than the test's 300 s, so CI reported a hang instead of the command to run
(test_bench_publish, run 46113462105). This says the command and a few lines of a line diff.
"""

import difflib
import itertools

import pytest


def same_as_generated(committed: str, made: str, fix: str, name: str = "the committed file") -> None:
    if committed == made:
        return
    diff = difflib.unified_diff(committed.splitlines(), made.splitlines(), name, "generated now", lineterm="", n=1)
    pytest.fail(f"{name} is stale: {fix}\n" + "\n".join(itertools.islice(diff, 40)), pytrace=False)
