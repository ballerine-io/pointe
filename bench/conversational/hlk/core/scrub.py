"""Nothing committed may hold a home path, a token shape, or a path outside /tmp. `check` refuses such a row;
`clean` rewrites free text before it is stored."""

import json
import re
from pathlib import Path

import getpass
import socket

HOME = str(Path.home())
USER = getpass.getuser()
HOST = socket.gethostname().split(".")[0]
REPLACE: list = []  # (text, stand-in) pairs the runner adds: the Pointe checkout, this repository
TOKEN = re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}|sk-[A-Za-z0-9]{20,}|AIza[\w-]{20,}|xi-api-key|[0-9a-f]{32,}(?![0-9a-f])")
HOMEISH = re.compile(r"/Users/[^\s\"'/]+|/home/[^\s\"'/]+|~/")
SHA_OK = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")


def clean(text: str) -> str:
    for old, new in sorted(REPLACE, key=lambda x: -len(x[0])):
        text = text.replace(old, new).replace(old.replace("/Users/", "/private/Users/", 1), new)
    text = text.replace(HOME, "~")
    if len(USER) > 3:
        text = re.sub(re.escape(USER), "[user]", text, flags=re.I)
    if len(HOST) > 3:
        text = re.sub(re.escape(HOST), "[host]", text, flags=re.I)
    text = re.sub(r"sk-ant-[A-Za-z0-9_\-]{6,}|sk-[A-Za-z0-9]{20,}|AIza[\w-]{20,}", "[key]", text)
    text = re.sub(r"/private/tmp/", "/tmp/", text)
    return HOMEISH.sub("[home]", text)


def problems(obj) -> list:
    """Every string in obj that holds a home path or a key-shaped token (hex digests of 40 or 64 are allowed)."""
    out = []

    def walk(x, where):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, f"{where}.{k}")
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{where}[{i}]")
        elif isinstance(x, str):
            if HOME in x or HOMEISH.search(x) or (len(USER) > 3 and USER.lower() in x.lower()):
                out.append(f"{where}: home path")
            for m in TOKEN.finditer(x):
                if not SHA_OK.match(m.group(0)) and len(m.group(0)) not in (40, 64):
                    out.append(f"{where}: key-shaped text")
    walk(obj, "row")
    return out


def check(row: dict) -> dict:
    found = problems(row)
    if found:
        raise ValueError("refused row: " + "; ".join(found[:5]))
    return row


def check_file(path: Path) -> list:
    bad = []
    for i, line in enumerate(path.read_text().splitlines()):
        if line.strip():
            bad += [f"{path.name}:{i + 1}: {p}" for p in problems(json.loads(line))]
    return bad
