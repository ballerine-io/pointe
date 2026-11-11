"""With no call connected the hook must stay out of the way: Claude Code's own dialog opens. Run with an isolated state dir and port."""

import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from hook_session import PluginSession  # noqa: E402
from rig import fresh_state, stop_daemon  # noqa: E402
from scenarios import TEST_MODEL, reset_repo  # noqa: E402

REPO = Path("/tmp/cv-repo-hook")
assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
reset_repo(REPO)
fresh_state()
session = PluginSession(REPO, "--model", TEST_MODEL, "--permission-mode", "default")
session.start()
try:
    session.type("/pointe:voice --name hooked")
    time.sleep(25)
    mark = len(session.screen)
    session.type("Use the Bash tool to run: touch from-terminal.txt")
    deadline = time.time() + 60
    while time.time() < deadline and "doyouwant" not in re.sub(r"\s+", "", session.screen[mark:]).lower():
        time.sleep(0.5)
    shown = "doyouwant" in re.sub(r"\s+", "", session.screen[mark:]).lower()
    print(("PASS" if shown else "FAIL"), " with no call, Claude Code's own dialog opens")
    if not shown:
        print(repr(session.screen[-500:]))
finally:
    session.stop()
    stop_daemon()
