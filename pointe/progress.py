"""Spoken progress while a session works. Off by default (the setting "progress.spoken"; "keep me posted" and "stop
updates" by voice).

After "Asking billing" there was silence until the answer, and a long silence reads as a dead call. On, and a session
has had the owner's request for FIRST_SECS without answering, Pointe says one short line, then one every EVERY_SECS:

    Billing is still working, 20 seconds in. Latest step: running the tests.

Every word is from the session's own record, never from a model: how long since the request went, and the newest tool
the session used since (step_of: the tool's name and its input decide, the session model's description never does). A
step is named in fixed words; a command is never said, and of a path only the file's name. With no step since the
request the line names none; with the same step as last time it says so.

Nothing is said after the session's turn ended (the answer follows by the usual rules), while it waits on the owner (its
read-out is the news), over anyone (the floor's rules, as for other unsolicited speech), or in a meeting, a hold, a
brain dump, a challenge or a briefing. A switch to another session or mode ends the updates for what the owner left, as
it stops speech. Muted, the line is text like every other line. Drive mode says it: it is short and names no screen.

The watch itself runs whether or not the lines are spoken: the screens show "<session> is working…" from it
(thinking.py).
"""

import os
import re
from dataclasses import dataclass

from artifacts import _EDITS, _TEST

FIRST_SECS, EVERY_SECS = 20.0, 45.0

_LEAD = r"^\W*(?:(?:ok(?:ay)?|so|hey|pointe|please|and)\W+)*"
_ON = re.compile(
    _LEAD + r"(?:keep me (?:posted|updated|in the loop)|(?:give|send) me (?:progress )?updates|"
    r"tell me how it(?:'s| is) going(?: as it works| while it works)?|(?:turn on )?progress updates(?: on)?)(?: please)?\W*$|"
    r"^\W*(?:תעדכן אותי(?: תוך כדי)?|תעדכני אותי|עדכוני התקדמות)\W*$", re.I)
_OFF = re.compile(
    _LEAD + r"(?:stop (?:the |progress )?updates|no more (?:progress )?updates|stop keeping me (?:posted|updated)|"
    r"(?:turn off )?progress updates off|stop updating me)(?: please)?\W*$|"
    r"^\W*(?:בלי עדכונים|תפסיק לעדכן(?: אותי)?|תפסיקי לעדכן(?: אותי)?|די עם העדכונים)\W*$", re.I)


def intent(text: str) -> bool | None:
    """A whole short utterance that turns the updates on (True) or off (False); None for anything else. "Keep me posted
    on what billing decides" and "tell billing to stop updates to the schema" are requests."""
    text = text.strip()
    if _ON.match(text):
        return True
    if _OFF.match(text):
        return False
    return None


# The words, on the page (ui_thinking.html) and in both apps (ThinkingCopy), word for word.
COPY = {
    "setting": "Progress updates",
    "hint": "While a session works on your request, Pointe says one short line after 20 seconds, then every 45.",
}

ON_LINE = "I'll keep you posted while a session works. Say \"stop updates\" to end it."
OFF_LINE = "No more updates."

_SEARCHES = {"grep", "glob", "ls", "search", "codesearch", "toolsearch"}
_AGENTS = {"task", "agent"}
_HEBREW = {"running the tests": "מריץ את הטסטים", "running a command": "מריץ פקודה", "searching the code": "מחפש בקוד",
           "searching the web": "מחפש ברשת", "reading a web page": "קורא דף אינטרנט",
           "running a helper agent": "מריץ סוכן עזר", "updating its task list": "מעדכן את רשימת המשימות",
           "using a tool": "משתמש בכלי", "editing a file": "עורך קובץ", "reading a file": "קורא קובץ"}


def step_of(tool: str, tool_input: dict | None) -> str:
    """What a tool use is called when said aloud: fixed words from the tool's name and its input. Never the command,
    never the model's description of it, never more of a path than the file's name."""
    name = (tool or "").lower()
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    path = tool_input.get("file_path") or tool_input.get("filePath") or tool_input.get("notebook_path") or tool_input.get("path")
    file = os.path.basename(str(path)) if isinstance(path, str) and path.strip() else ""
    if name in ("bash", "shell"):
        return "running the tests" if _TEST.search(str(tool_input.get("command") or "")) else "running a command"
    if name in _EDITS:
        return f"editing {file}" if file else "editing a file"
    if name == "read":
        return f"reading {file}" if file else "reading a file"
    if name in _SEARCHES:
        return "searching the code"
    if name == "websearch":
        return "searching the web"
    if name == "webfetch":
        return "reading a web page"
    if name in _AGENTS:
        return "running a helper agent"
    if name in ("todowrite", "taskcreate", "taskupdate"):
        return "updating its task list"
    return "using a tool"


def elapsed(secs: float, hebrew: bool = False) -> str:
    """How long, as a person says it, never more than has passed: tens of seconds, then half minutes, then hours."""
    secs = int(secs)
    if secs < 60:
        tens = max(10, secs // 10 * 10)
        return f"{tens} שניות" if hebrew else f"{tens} seconds"
    if secs >= 3600:
        hours = secs // 3600
        if hebrew:
            return "שעה" if hours == 1 else "שעתיים" if hours == 2 else f"{hours} שעות"
        return "an hour" if hours == 1 else f"{hours} hours"
    minutes, half = secs // 60, secs % 60 >= 30
    if hebrew:
        whole = "דקה" if minutes == 1 else "שתי דקות" if minutes == 2 else f"{minutes} דקות"
        return f"{whole} וחצי" if half else whole
    if minutes == 1:
        return "a minute and a half" if half else "a minute"
    return f"{minutes} and a half minutes" if half else f"{minutes} minutes"


def _hebrew_step(step: str) -> str:
    if step in _HEBREW:
        return _HEBREW[step]
    verb, _, file = step.partition(" ")
    return f"{'עורך' if verb == 'editing' else 'קורא'} את {file}"


def line(name: str, secs: float, step: str | None, new: bool, hebrew: bool = False) -> str:
    """One update. `step`: the newest step since the request (step_of), None when the record shows none; `new`: it is
    not the step the last update named."""
    if hebrew:
        base = f"{name} עדיין עובד, כבר {elapsed(secs, True)}."
        if step is None:
            return base
        return f"{base} {'הצעד האחרון' if new else 'עדיין באותו צעד'}: {_hebrew_step(step)}."
    if step is None:
        return f"{name} is still working, {elapsed(secs)} in."
    if new:
        return f"{name} is still working, {elapsed(secs)} in. Latest step: {step}."
    return f"{name} is still on the same step, {elapsed(secs)} in: {step}."


@dataclass
class Ask:
    since: float  # the owner's request reached the session
    said_at: float = 0.0  # the last update
    said: int = 0
    step: str | None = None  # the step that update named


class Watch:
    """The sessions that have a request of the owner's and have not answered, on this call."""

    def __init__(self) -> None:
        self.asks: dict[str, Ask] = {}

    def asked(self, session_id: str, now: float) -> None:
        self.asks[session_id] = Ask(since=now)

    def done(self, session_id: str) -> None:
        self.asks.pop(session_id, None)

    def clear(self) -> None:
        self.asks.clear()

    def due(self, now: float) -> list[str]:
        return [sid for sid, ask in self.asks.items()
                if (now - ask.said_at >= EVERY_SECS if ask.said else now - ask.since >= FIRST_SECS)]

    def said(self, session_id: str, now: float, step: str | None) -> None:
        ask = self.asks.get(session_id)
        if ask is not None:
            ask.said_at, ask.said, ask.step = now, ask.said + 1, step

    def newest(self) -> str | None:
        return max(self.asks, key=lambda sid: self.asks[sid].since) if self.asks else None
