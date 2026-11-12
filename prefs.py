"""The user's settings, owned by the daemon so the page and the phone show and change the same thing.
~/.claude-voice/prefs.json, 0600. Only known keys, with their types; anything else is refused."""

import json
import os
from pathlib import Path

# key -> (default, allowed values or a type)
SCHEMA: dict[str, tuple] = {
    "meeting.default_mode": ("listening", ("listening", "participating")),
    "meeting.auto_lookups": (False, bool),
    "meeting.notes_language": ("auto", ("auto", "en", "he")),
    "meeting.consented": (False, bool),  # the consent step was shown and accepted once on this Mac
    "voice_lock": ("off", ("off", "approvals", "commands", "everything")),  # set only through /voice/voiceprint
    "microphone": ("always", ("always", "ptt")),  # push to talk: audio is heard only while a press holds it open
    "alerts.watch_approve": (False, bool),  # Approve on a notification (iPhone, mirrored to the watch): no Face ID
    "show.on_phone": (False, bool),  # show while it says on the phone: off until enabled (the page always shows it)
}


class Prefs:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.values: dict = {}
        try:
            loaded = json.loads(path.read_text())
            self.values = {k: v for k, v in loaded.items() if k in SCHEMA and _ok(k, v)}
        except (OSError, ValueError):
            pass

    def get(self, key: str):
        return self.values.get(key, SCHEMA[key][0])

    def all(self) -> dict:
        return {k: self.get(k) for k in SCHEMA}

    def update(self, changes: dict) -> dict:
        bad = [k for k, v in changes.items() if k not in SCHEMA or not _ok(k, v)]
        if bad:
            raise ValueError(f"not a setting, or a wrong value: {', '.join(sorted(bad))}")
        self.values.update(changes)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.touch(mode=0o600)
        tmp.write_text(json.dumps(self.values, indent=1))
        os.replace(tmp, self.path)
        return self.all()


def _ok(key: str, value) -> bool:
    allowed = SCHEMA[key][1]
    return isinstance(value, allowed) if isinstance(allowed, type) else value in allowed
