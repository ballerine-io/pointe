"""A test that opens windows on this Mac runs in CI, not on the Mac a person is working at.

The Mac smoke (apps/macos/e2e/smoke.py), the Mac app's XCUITests and the iPhone app's UI tests in the Simulator put
windows on the screen, take the keyboard focus and, for some, move the pointer: the person at the Mac cannot work while
they run. Every script that starts one calls `require` first. It lets the run through in CI (`CI=true`, which GitHub
Actions sets) or when the person asked for it on this Mac (`POINTE_UI_LOCAL=1`); otherwise it prints one line and exits 2.

    python3 -I tools/ui_guard.py "<what is about to run>"     for a shell script: exit 0 to go on, 2 with the line

A script run with `python -I` has no folder of its own on sys.path, so the drivers load this file by its path (runpy).
An allowed run also sets TEST_RUNNER_POINTE_UI_LOCAL=1 for the xcodebuild it starts: xcodebuild hands the test runner
the variables named TEST_RUNNER_*, and the UI test bundles check it themselves (UIGuard in each bundle).
"""

import os
import sys

WORKFLOW = "ui.yml"


def allowed(env=None) -> bool:
    env = os.environ if env is None else env
    return env.get("CI") == "true" or env.get("POINTE_UI_LOCAL") == "1"


def refusal(what: str) -> str:
    return (f"refused: {what} opens windows and takes the keyboard and pointer on this Mac. It runs in CI: push, or "
            f"`gh workflow run {WORKFLOW}`, and read its artifacts. To run it here anyway: POINTE_UI_LOCAL=1.")


def require(what: str) -> None:
    if not allowed():
        print(refusal(what), file=sys.stderr)
        raise SystemExit(2)
    os.environ.setdefault("TEST_RUNNER_POINTE_UI_LOCAL", "1")


if __name__ == "__main__":
    require(" ".join(sys.argv[1:]) or "this UI test")
