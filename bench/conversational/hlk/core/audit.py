"""The answer keys sit on the machine the agent's Bash can reach. This scans every agent transcript for a tool input
that names a path outside the item's folder; the Pointe plugin path is the one exception, Pointe arm only. Such a row is
invalid_out_of_tree: excluded, and counted per arm on the page."""

import json
import re

PATH = re.compile(r"(?<![\w.])(/(?:[\w.@+-]+/)*[\w.@+-]+)")
SYSTEM = ("/usr/", "/bin/", "/opt/homebrew/", "/dev/null", "/dev/", "/etc/", "/Library/", "/System/", "/private/var/folders/",
          "/var/folders/", "/sbin/")


def outside(tool_inputs: list, slot: str, allowed: tuple = ()) -> list:
    """Paths named in tool inputs that are neither inside slot, nor system paths, nor allowed."""
    slots = (slot.rstrip("/"), slot.replace("/tmp/", "/private/tmp/", 1).rstrip("/"))
    found = []
    for item in tool_inputs:
        text = json.dumps(item.get("input") or {})
        for m in PATH.finditer(text.replace("\\/", "/")):
            p = m.group(1)
            if len(p) < 4 or any(p.startswith(s) for s in slots) or any(p.startswith(s) for s in SYSTEM):
                continue
            if any(p.startswith(a) for a in allowed):
                continue
            if p.startswith("/tmp/pccb/") or p.startswith("/tmp/") or p.startswith("/private/tmp/") or p.startswith("/Users/") \
                    or p.startswith("/home/") or p.startswith("/var/") or p.startswith("/Volumes/"):
                found.append(f"{item.get('tool')}: {p}")
        if re.search(r"pccb-keys|bench/conversational|(^|[\s\"'=])\.\./\.\.", text):
            found.append(f"{item.get('tool')}: names the answer keys, the bench, or climbs out with ../..")
    return found
