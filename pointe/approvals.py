"""The approvals record: every answer to a permission request that went through Pointe, kept in the daemon's journal and
shown on the page and in both apps (docs/features/approvals-record.md).

When an answer reaches its session, the daemon writes one journal line: MARK, then JSON with the session, the request's
id, the decision, how it was given (by voice, a tap, a notification's action), the exact request as the card showed it
(the tool, then its input; secret-looking values masked, as everywhere in the journal) and, for a spoken answer, the
voice lock's level and the score of the voice that said it. Nothing else is stored anywhere: the record is read back
from the journal (journal.jsonl and the one older file it rotates to), so it is as old as the journal is long, and a
journal that was deleted is an empty record. An answer given in the session's own terminal never went through Pointe
and is not here.
"""

import json
from pathlib import Path

from readout import mask

# The words, on the page (ui_approvals.html) and in both apps (ApprovalsCopy), word for word.
COPY = {
    "title": "Approvals record",
    "lede": "Every answer to a request that went through Pointe on this Mac, newest first. An answer given in a session's own terminal is not here.",
    "empty": "No request has been answered through Pointe yet.",
    "allow": "Approved",
    "deny": "Denied",
    "voice": "by voice",
    "tap": "by a tap",
    "notification": "from a notification",
    "other": "by Pointe",
    "score": "Voice lock {lock}: score {score}",
    "unscored": "Voice lock {lock}: the voice was not scored",
    "lock_off": "Voice lock off: the voice was not checked",
    "cut": "The request was longer than the record keeps: this is its start.",
    "failed": "The record did not load from the Mac.",
}

MARK = "approval "
MAX_REQUEST_CHARS = 4000  # a request longer than this is kept cut, and says so: the card showed the same cut
LIMIT = 200  # the newest this many are returned
_BY = {"tapped": "tap", "from a notification": "notification"}
_DECISIONS = ("allow", "deny")


def by(how: str) -> str:
    """How the answer was given, from the words the daemon's own log line uses."""
    if how.startswith("user said:"):
        return "voice"
    return _BY.get(how, "other")


def event(*, session: str, machine: str | None, request_id: str, decision: str, how: str, request: str, lock: str,
          score: float | None) -> str:
    """The journal line for one answer. `score`: the voice lock's score of the spoken answer; None for a tap, and for
    a voice the lock did not score."""
    shown = mask(request or "")
    record = {"session": session, "request_id": request_id, "decision": decision, "by": by(how),
              "request": shown[:MAX_REQUEST_CHARS], "lock": lock, "score": score if by(how) == "voice" else None}
    if machine:
        record["machine"] = machine
    if len(shown) > MAX_REQUEST_CHARS:
        record["cut"] = True
    return MARK + json.dumps(record, ensure_ascii=False, sort_keys=True)


def parse(line: dict) -> dict | None:
    """One journal entry as a record, or None when it is not a whole approval line."""
    text = line.get("event")
    if not isinstance(text, str) or not text.startswith(MARK + "{"):
        return None
    try:
        r = json.loads(text[len(MARK):])
    except ValueError:
        return None
    if not isinstance(r, dict) or r.get("decision") not in _DECISIONS or not r.get("session") or not r.get("request_id"):
        return None
    score = r.get("score")
    return {"at": str(line.get("at") or ""), "session": str(r["session"]), "machine": r.get("machine") or None,
            "request_id": str(r["request_id"]), "decision": r["decision"], "by": str(r.get("by") or "other"),
            "request": str(r.get("request") or ""), "cut": bool(r.get("cut")), "lock": str(r.get("lock") or "off"),
            "score": float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None}


def read(paths: list[Path], limit: int = LIMIT) -> list[dict]:
    """Every approval in these journal files (oldest file first), newest first, at most `limit`."""
    found: list[dict] = []
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for raw in f:
                    if MARK not in raw:
                        continue
                    try:
                        record = parse(json.loads(raw))
                    except ValueError:
                        continue
                    if record is not None:
                        found.append(record)
        except OSError:
            continue
    return found[::-1][:limit]
