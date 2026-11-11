"""Every test runs against a throwaway state dir: daemon.py reads CLAUDE_VOICE_STATE once, at import,
and a test that imports it first must never point it at the live ~/.claude-voice."""

import os
import tempfile
from pathlib import Path

_STATE = Path(tempfile.mkdtemp(prefix="cv-test-state-"))
(_STATE / "token").write_text("test-token")
os.environ["CLAUDE_VOICE_STATE"] = str(_STATE)
