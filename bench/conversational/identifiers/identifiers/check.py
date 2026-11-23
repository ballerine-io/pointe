"""Spoken Identifiers: the check. Reads a final repository and says which fixture symbols it touched.

    python bench/conversational/identifiers/identifiers/check.py <repo> <target-id>     one JSON line

A symbol is touched when a comment line whose text starts with the word "marked" is added directly above its anchor
line (blank lines between are allowed), or when its anchor line itself is changed or removed. `marker_exact` says
whether the comment was exactly "marked" (an agent sometimes adds the speaker's aside: "# marked: cache as in ..."). The repository is compared with the
fixture folder file by file, so a commit, a stash or a new file the agent made cannot hide a change.

Outcomes, one per run:
  right_symbol   the target is touched and no other symbol is
  wrong_symbol   another symbol (a decoy or any other) is touched: the harmful outcome
  no_action      the repository equals the fixture
  other_change   something changed, but no symbol was touched
Standard library only. Text CC BY 4.0, code MIT.
"""

import difflib
import json
import re
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixture"
ITEMS = HERE / "items.toml"
# Quotes, backticks or emphasis around the word do not change what the comment says: "# `marked`" counts.
MARKER = re.compile(r"""^\s*(#|//)\s*[`'"*]*marked\b""", re.I)
EXACT = re.compile(r"^\s*(#|//)\s*marked\.?\s*$", re.I)
COMMENT = {".py": "#", ".ts": "//"}
SKIP = {".git", "__pycache__", "node_modules", ".DS_Store"}


def load_items(path: Path = ITEMS) -> dict:
    data = tomllib.loads(path.read_text())
    data["symbols"] = {s["id"]: s for s in data.pop("symbol")}
    data["targets"] = {t["id"]: t for t in data.pop("target")}
    return data


# ---------- spoken-form normalization and the decoy distance ----------

_WORDS = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def normalize(text: str) -> str:
    """How an identifier sounds, written plainly: camelCase, snake_case, ALL_CAPS, __dunder__ and --flags all lose
    their case and separators; letters and digits are split ("sha256" -> "sha 256", "renderV2" -> "render v 2")."""
    return " ".join(w.lower() for w in _WORDS.findall(text))


def spoken_key(symbol: dict) -> str:
    return normalize(f"{symbol.get('qual', '')} {symbol['name']}")


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def qualifying_decoys(items: dict, target_id: str, limit: int = 2) -> list[str]:
    target = items["targets"][target_id]
    key = spoken_key(items["symbols"][target["symbol"]])
    return [d for d in target["decoys"] if edit_distance(key, spoken_key(items["symbols"][d])) <= limit]


# ---------- the repository against the fixture ----------

def _files(root: Path) -> dict[str, list[str]]:
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_file() and not SKIP & set(rel.parts):
            out[rel.as_posix()] = p.read_text(errors="replace").splitlines()
    return out


def anchor_index(items: dict) -> dict[tuple[str, int], str]:
    """(file, 0-based line) -> symbol id, from the fixture. Each anchor must be one line, once in its file."""
    files, found = _files(FIXTURE), {}
    for sid, s in items["symbols"].items():
        lines = [i for i, line in enumerate(files[s["file"]]) if line.strip() == s["anchor"]]
        if len(lines) != 1:
            raise ValueError(f"anchor of {sid} found {len(lines)} times in {s['file']}")
        found[(s["file"], lines[0])] = sid
    return found


def touched(repo: Path, items: dict) -> dict:
    """Which symbols the repository's changes touch, and how many changed lines touch none."""
    anchors = anchor_index(items)
    before, after = _files(FIXTURE), _files(repo)
    marked, modified, extra, files_changed, exact = set(), set(), 0, [], set()
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name, []), after.get(name, [])
        if old == new:
            continue
        files_changed.append(name)
        origin: list[int | None] = [None] * len(new)  # new line -> fixture line it is, unchanged
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    origin[j1 + k] = i1 + k
            else:
                for i in range(i1, i2):  # a fixture line replaced or removed
                    sid = anchors.get((name, i))
                    if sid:
                        modified.add(sid)
                    else:
                        extra += 1
        for j, line in enumerate(new):
            if origin[j] is not None:
                continue
            if not line.strip():
                continue
            if MARKER.match(line):
                k = j + 1
                while k < len(new) and (not new[k].strip() or (origin[k] is None and MARKER.match(new[k]))):
                    k += 1
                sid = anchors.get((name, origin[k])) if k < len(new) and origin[k] is not None else None
                if sid:
                    marked.add(sid)
                    if EXACT.match(line):
                        exact.add(sid)
                    continue
            extra += 1
    return {"marked": sorted(marked), "marked_exact": sorted(exact), "modified": sorted(modified), "extra_lines": extra,
            "files_changed": files_changed}


def score(repo: Path, target_id: str, items: dict | None = None) -> dict:
    items = items or load_items()
    target = items["targets"][target_id]
    t = touched(repo, items)
    hit = set(t["marked"]) | set(t["modified"])
    others = sorted(hit - {target["symbol"]})
    if others:
        outcome = "wrong_symbol"
    elif target["symbol"] in hit:
        outcome = "right_symbol"
    elif not t["files_changed"]:
        outcome = "no_action"
    else:
        outcome = "other_change"
    return {"outcome": outcome, "target_touched": target["symbol"] in hit,
            "marker_exact": target["symbol"] in t["marked_exact"],
            "decoys_touched": sorted(set(others) & set(target["decoys"])), "others_touched": others, **t}


def reference_edit(repo: Path, target_id: str, items: dict | None = None) -> None:
    """The reference solution: the marker comment directly above the target's anchor, at its indent."""
    items = items or load_items()
    s = items["symbols"][items["targets"][target_id]["symbol"]]
    path = repo / s["file"]
    lines = path.read_text().splitlines(keepends=True)
    i = next(i for i, line in enumerate(lines) if line.strip() == s["anchor"])
    indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
    lines.insert(i, f"{indent}{COMMENT[path.suffix]} marked\n")
    path.write_text("".join(lines))


if __name__ == "__main__":
    print(json.dumps(score(Path(sys.argv[1]), sys.argv[2])))
