"""The user's settings, owned by the daemon so the page and the phone show and change the same thing.
~/.claude-voice/prefs.json, 0600. Only known keys, with their types; anything else is refused."""

import json
import os
from pathlib import Path

from briefing import valid_days, valid_time
from newsession import valid_folders
from nightshift import HOURS, MESSAGES, valid_hours, valid_messages

# key -> (default, allowed values, a type, or a check)
SCHEMA: dict[str, tuple] = {
    "meeting.default_mode": ("listening", ("listening", "participating")),
    "meeting.auto_lookups": (False, bool),
    "meeting.notes_language": ("auto", ("auto", "en", "he")),
    "meeting.consented": (False, bool),  # the consent step was shown and accepted once on this Mac
    "voice_lock": ("off", ("off", "approvals", "commands", "everything")),  # set only through /voice/voiceprint
    # ptt: audio is heard only while a press holds it open. addressed (addressed.py): heard always, acted on only when
    # the words say the name of Pointe or of a session.
    "microphone": ("always", ("always", "addressed", "ptt")),
    "reports.tones": (False, bool),  # one sound per session (tones.py): a short tone before a background session's report
    "conflicts.on": (True, bool),  # check two sessions' reports against each other
    "conflicts.spoken": (True, bool),  # say an alarm, or show it as a card only
    "briefings.time": ("", valid_time),  # "HH:MM" local, or "" for no scheduled briefing
    "briefings.days": ([0, 1, 2, 3, 4, 5, 6], valid_days),  # Monday is 0
    "briefings.length": ("normal", ("short", "normal", "full")),
    "briefings.speak_on_connect": (True, bool),  # a scheduled briefing not heard yet is offered when a call starts
    "briefings.skip_empty": (False, bool),  # a quiet night raises no alert
    "alerts.watch_approve": (False, bool),  # Approve on a notification (iPhone, mirrored to the watch): no Face ID
    "show.on_phone": (False, bool),
    "whisper": (False, bool),  # whisper mode (whisper.py): a quieter bot, a raised microphone, short replies  # show while it says on the phone: off until enabled (the page always shows it)
    "dictionary.learn": (True, bool),  # a correction teaches the names it fixed; suggestions from session notes
    # Folders a new session may start in, beside those of current and recent sessions (docs/design/new-session.md).
    # Changed only at the Mac: daemon.prefs_set refuses it from the phone and from a page over the network.
    "sessions.folders": ([], valid_folders),
    # A night shift's caps and whether its blockers may alert overnight (docs/design/night-shift.md).
    "nightshift.hours": (HOURS, valid_hours),  # a shift ends after this many hours, at most 12
    "nightshift.messages": (MESSAGES, valid_messages),  # messages a shift may send to sessions, at most 200
    "nightshift.notify": (False, bool),  # off: a blocked session raises no alert until morning
    "thinking.cue": (True, bool),  # the waiting sound: one soft tone when a reply takes long (thinking.py)
    "progress.spoken": (False, bool),  # say how a session is doing while it works on a request (progress.py)
    "turns.patience": ("normal", ("quick", "normal", "patient")),  # wait before answering (turns.LEVELS): how long a pause ends a sentence
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
        value = self.values.get(key, SCHEMA[key][0])
        return list(value) if isinstance(value, list) else value  # never the schema's own default list

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
    if isinstance(allowed, type):
        return isinstance(value, allowed)
    return allowed(value) if callable(allowed) else value in allowed
