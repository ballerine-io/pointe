#!/usr/bin/env python3
"""An old part of Pointe against a new one fails in one sentence, never in a traceback or a bare status.

The parts are the scripts in bin/, the Claude Code plugin's hooks and commands, the channel, the CLI, and the voice or
host they call on this machine (daemon.py, node.py). Each caller says who it is in one header:

    X-Pointe-Client: <part>/<version> api=<n>

The one that answers serves api MIN_API to API. A caller outside that range gets 426 and
{"error": <one sentence>, "need": {"api": [min, max]}, "have": {"part", "version", "api"}, "how": <the command>}.
A request with no header is api 1: every script released before the header existed, served as before.

The caller's half is `sentence`: any answer that is not a 200 with JSON becomes one printed line. bin/voice-ask runs
this file for it, so the words exist once. Standard library only, and the machine's own python3 (3.9 on a Mac) runs
it: a host imports it, and so does `python3 -I` in a script.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

API = 2  # the local HTTP contract between bin/, hooks/, channel/ and the voice or host on this machine
MIN_API = 1  # the oldest caller still served: a script with no header at all
HEADER = "X-Pointe-Client"
STATUS = 426  # Upgrade Required (RFC 9110): no version both sides speak
PLUGIN_UPDATE = "claude plugin marketplace update pointe && claude plugin update pointe@pointe && pointe restart"
_VALUE = re.compile(r"([a-z][a-z0-9-]{0,39})/([0-9A-Za-z.+-]{1,40}) api=([0-9]{1,6})")


def version() -> str:
    """This copy's version, from the manifest next to pointe/ (the one the page and the apps show)."""
    try:
        return str(json.loads((Path(__file__).resolve().parents[1] / ".claude-plugin" / "plugin.json").read_text())["version"])
    except (OSError, ValueError, KeyError):
        return "0"


def header(part: str, version: str) -> str:
    """What a caller of this copy sends."""
    return f"{part}/{version} api={API}"


def parse(value) -> tuple[str, str, int] | None:
    """(part, version, api) from the header, or None for one that is absent or not in the form above."""
    found = _VALUE.fullmatch(value.strip()) if isinstance(value, str) else None
    return (found.group(1), found.group(2), int(found.group(3))) if found else None


def refusal(value, version: str, api: int = API, min_api: int = MIN_API) -> dict | None:
    """The 426 body for a caller this copy (`version`) cannot serve, or None for one it can. A missing or unreadable
    header is the oldest caller, not an error: an old script cannot be made to send it."""
    who = parse(value)
    if who is None:
        return None
    part, theirs, offered = who
    if min_api <= offered <= api:
        return None
    if offered > api:
        how = "pointe restart"
        error = (f"The Pointe running on this machine is {version}, older than the {part} that called it ({theirs}). "
                 f"Start the newer one: {how}")
    else:
        how = PLUGIN_UPDATE if part in ("plugin", "hook", "channel") else "pointe update"
        error = (f"The Pointe {part} that made this call is {theirs}, too old for the Pointe running on this machine "
                 f"({version}). Update it: {how}")
    return {"error": error, "need": {"api": [min_api, api]}, "have": {"part": part, "version": theirs, "api": offered},
            "how": how}


def sentence(status: int, body: bytes | str, port: int | str = "") -> str:
    """One line for a caller to print when the answer is not a 200 with JSON. A structured refusal's own sentence
    first; else what the status most likely means between two versions of Pointe."""
    where = f" on port {port}" if port else ""
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body or "")
    try:
        got = json.loads(text)
    except ValueError:
        got = None
    if isinstance(got, dict) and isinstance(got.get("error"), str) and got["error"].strip():
        return "Pointe: " + " ".join(got["error"].split())[:400]
    detail = got.get("detail") if isinstance(got, dict) else None
    if isinstance(detail, str) and detail.strip() and detail not in ("Not Found", "Method Not Allowed"):
        return "Pointe: " + " ".join(detail.split())[:400]  # the route's own reason ("no call is up"), not a version's
    if not status:
        return f"Pointe: nothing answered{where}. Start it: pointe start"
    if status == 200:
        return (f"Pointe: the answer{where} was not what this version reads: another version of Pointe is running. "
                "pointe doctor names it and how to update")
    if status == STATUS:
        return f"Pointe: the Pointe running{where} and this command are different versions. pointe doctor names both"
    if status in (401, 403):
        return (f"Pointe: the Pointe running{where} refused this call ({status}): it is another version, or was started "
                "from another install. pointe doctor names both and how to update")
    if status in (404, 405):
        return (f"Pointe: the Pointe running{where} does not know this request ({status}): it is older than this "
                "command. Start the newer one: pointe restart")
    return f"Pointe: the Pointe running{where} answered {status}. pointe doctor says what is wrong"


if __name__ == "__main__":  # bin/voice-ask: `skew.py sentence <status> [port]`, the body on stdin
    if len(sys.argv) >= 3 and sys.argv[1] == "sentence":
        code = int(sys.argv[2]) if sys.argv[2].isdigit() else 0
        print(sentence(code, sys.stdin.buffer.read(1 << 20), sys.argv[3] if len(sys.argv) > 3 else ""))
    elif len(sys.argv) == 2 and sys.argv[1] == "api":
        print(API)
    else:
        raise SystemExit("usage: skew.py sentence <status> [port] < body | skew.py api")
