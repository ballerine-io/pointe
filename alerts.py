"""Alerts that reach the user away from the screen: iPhone notifications (mirrored to the watch) and desktop
notifications from the page. docs/features/alerts.md.

A notification sits on a lock screen and a wrist, so it shows less than the page's approval card:
- a permission shows the read-out form (readout.py's allowlist, through guards.readable_request) and nothing else; a
  request that cannot be read out shows only its tool's name, and the exact text stays in the app and the page;
- anything that looks like a credential is not shown at all (readout.redact, the same rule the voice follows);
- an Approve on a notification can reach only a request that a spoken yes could approve (readable, nothing withheld),
  bound to its request id. The daemon checks that again when the answer arrives (`approvable`).
"""

import re

import readout

KEEP = 64  # recent requests remembered; a request older than that is no longer pending anyway

# (session id, request id) -> {"tool", "readable"}, recorded when the request arrives. Keyed by session as well: a node
# picks its own request ids, so one equal to a local pending id must not replace that request's record.
_REQUESTS: dict[tuple[str, str], dict] = {}

_TOOL = re.compile(r"^[\w.:-]{1,64}$")


def note_request(session_id: str, request_id: str, tool: str, readable: str | None) -> None:
    key = (session_id, request_id)
    _REQUESTS.pop(key, None)
    _REQUESTS[key] = {"tool": tool, "readable": readable or ""}
    while len(_REQUESTS) > KEEP:
        # Each session's newest request is the one it can still have pending: a session (a node) that sends many
        # cannot push another session's newest out. Only when every record is a newest does the oldest go.
        newest = {sid: rid for sid, rid in _REQUESTS}
        old = next((k for k in _REQUESTS if newest[k[0]] != k[1]), next(iter(_REQUESTS)))
        del _REQUESTS[old]


def _shown(session_id: str, request_id: str) -> str:
    """The read-out form when it may be shown, else empty."""
    return (_REQUESTS.get((session_id, request_id)) or {}).get("readable", "")  # readable_request already ran readout.redact


def approvable(session_id: str, request_id: str) -> bool:
    """A notification's Approve may answer it: the notification showed what a spoken yes would approve."""
    return bool(_shown(session_id, request_id))


def permission_alert(session: str, session_id: str, request_id: str, at: float, title: str = "") -> dict:
    """`title` names the session for the person, when that differs from its name (its machine, "shop · devbox")."""
    shown = _shown(session_id, request_id)
    tool = (_REQUESTS.get((session_id, request_id)) or {}).get("tool", "")
    tool = tool if _TOOL.match(tool or "") else "a tool"
    body = shown or f"{tool}: open Pointe to see the exact request"
    return {"id": f"permission:{request_id}", "kind": "permission", "session": session, "request_id": request_id,
            "title": f"{title or session} needs approval", "body": body, "text": body, "approvable": bool(shown), "at": at}


def question_alert(session: str, need: str, since: float) -> dict:
    """A session finished its turn waiting on the user. No actions: answering it takes words."""
    body = need if need and readout.redact(need) and not _hidden(need) else "open Pointe to see what it needs"
    return {"id": f"question:{session}:{int(since)}", "kind": "question", "session": session,
            "title": f"{session} needs you", "body": body, "text": body, "approvable": False, "at": since}


def hand_alert(meeting: str, n: int, line: str, at: float) -> dict:
    """In a meeting, Pointe has a point to make and waits for the owner's go-ahead."""
    body = line if line and readout.redact(line) and not _hidden(line) else "open Pointe to hear it"
    return {"id": f"hand:{meeting}:{n}", "kind": "hand", "title": "Pointe wants to speak", "body": body, "text": body,
            "approvable": False, "at": at}


def briefing_alert(briefing_id: str, when: str, at: float) -> dict:
    """A scheduled briefing is ready and not heard yet. No actions: hearing it is a tap in Pointe or "yes" on a call."""
    body = f"Your {when} briefing is ready."
    return {"id": f"briefing:{briefing_id}", "kind": "briefing", "title": "Pointe", "body": body, "text": body,
            "approvable": False, "at": at}


def conflict_alert(conflict_id: str, a: str, b: str, at: float) -> dict:
    """Two sessions disagree. Names only: their claims quote the sessions' messages, so they stay in the app and the page."""
    body = f"{a} and {b} disagree. Open Pointe to see both claims."
    return {"id": f"conflict:{conflict_id}", "kind": "conflict", "title": "Two sessions disagree", "body": body,
            "text": body, "approvable": False, "at": at}


def _hidden(text: str) -> bool:
    return readout._hidden(text.replace("\n", " "))
