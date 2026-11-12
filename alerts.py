"""Alerts that reach the user away from the screen: iPhone notifications (mirrored to the watch) and desktop
notifications from the page. Feature 7 in docs/plans/next-features.md.

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

_REQUESTS: dict[str, dict] = {}  # request id -> {"tool", "readable"}, recorded when the request arrives

_TOOL = re.compile(r"^[\w.:-]{1,64}$")


def note_request(request_id: str, tool: str, readable: str | None) -> None:
    _REQUESTS.pop(request_id, None)
    _REQUESTS[request_id] = {"tool": tool, "readable": readable or ""}
    while len(_REQUESTS) > KEEP:
        _REQUESTS.pop(next(iter(_REQUESTS)))


def _shown(request_id: str) -> str:
    """The read-out form when it may be shown, else empty."""
    return (_REQUESTS.get(request_id) or {}).get("readable", "")  # readable_request already ran readout.redact


def approvable(request_id: str) -> bool:
    """A notification's Approve may answer it: the notification showed what a spoken yes would approve."""
    return bool(_shown(request_id))


def permission_alert(session: str, request_id: str, at: float) -> dict:
    shown = _shown(request_id)
    tool = (_REQUESTS.get(request_id) or {}).get("tool", "")
    tool = tool if _TOOL.match(tool or "") else "a tool"
    body = shown or f"{tool}: open Pointe to see the exact request"
    return {"id": f"permission:{request_id}", "kind": "permission", "session": session, "request_id": request_id,
            "title": f"{session} needs approval", "body": body, "text": body, "approvable": bool(shown), "at": at}


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


def _hidden(text: str) -> bool:
    return readout._hidden(text.replace("\n", " "))
