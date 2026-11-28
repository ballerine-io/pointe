"""How long a permission request for a shell command takes to read out, over a corpus of agents' own commands.

A spoken yes approves what was read (pointe/guards.py `spoken_request`): the allowlist's short form when there is one
(pointe/readout.py), else the command word for word, symbol by symbol. This counts, over bench/results/readout_corpus.jsonl,
how many commands are read word for word and how long each read-out takes.

The corpus: every Bash command the dialogue suite's sessions asked to run (bench/results/*/dialogues, their
PreToolUse and PermissionRequest hooks), every approval request the HLK runs logged (bench/conversational/hlk/results),
the approvals journal fixture, and commands typical of Claude Code and Codex sessions written for this (source
"synthetic"). The hooks log a command cut at 300 characters, and a cut one is kept as cut: its read-out is longer in
the session than here. `seen` is how often a command was asked for; the shares are of distinct commands unless --weighted.
`cwd` is the project folder, taken from the first project path in the command. These folders are not on this disk, so
a module the command imports that is not in the standard library is taken to be the project's own (as it was in the
session), which is what decides whether `python3 -c` code has a short form.

Length: words as a text-to-speech voice says them, "-name" as "dash name" and "hero.png" as "hero dot png" (each run of
letters or digits a word, each symbol a word; quotes are not said). Seconds at readout.WORDS per ten seconds.

  uv run --locked python -I bench/readout_bench.py [--weighted] [--list verbatim|short|tap]
"""

import argparse
import json
import os
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]

import guards  # noqa: E402
import readout  # noqa: E402

WORDS_PER_SEC = readout.WORDS / 10
_SAID = re.compile(r"[A-Za-z0-9]+|[^\sA-Za-z0-9'\"_,…]")


def spoken_words(text: str) -> int:
    return len(_SAID.findall(text))


def measure(row: dict) -> tuple[str, str | None, float]:
    """(kind, read-out, seconds): kind is "short", "verbatim", or "tap" (nothing is said: a secret or a question)."""
    isfile, cwd = os.path.isfile, row["cwd"]

    def project_module(path: str) -> bool:
        folder, name = os.path.split(path)
        module = os.path.basename(folder) if name == "__init__.py" else name.removesuffix(".py")
        if os.path.dirname(folder if name == "__init__.py" else path) == cwd:
            return module not in sys.stdlib_module_names
        return isfile(path)

    os.path.isfile = project_module
    try:
        said = guards.spoken_request("Bash", {"command": row["command"]}, cwd)
    finally:
        os.path.isfile = isfile
    if said is None:
        return "tap", None, 0.0
    kind = "verbatim" if guards.VERBATIM in said else "short"
    return kind, said, spoken_words(said) / WORDS_PER_SEC


def first_program(command: str) -> str:
    for word in re.split(r"[\s;&|()]+", command.strip()):
        if word and not re.fullmatch(r"[A-Za-z_]\w*=\S*", word):
            return word
    return ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weighted", action="store_true", help="count each command as often as it was asked for")
    parser.add_argument("--list", choices=("verbatim", "short", "tap"))
    args = parser.parse_args()
    rows = [json.loads(line) for line in (ROOT / "bench/results/readout_corpus.jsonl").read_text().splitlines() if line]
    results = []
    for row in rows:
        kind, said, secs = measure(row)
        results += [(row, kind, said, secs)] * (row["seen"] if args.weighted else 1)
    kinds = Counter(kind for _, kind, _, _ in results)
    said = [secs for _, kind, _, secs in results if kind != "tap"]
    total = len(results)
    print(f"{total} commands ({'weighted by times asked' if args.weighted else 'distinct'})")
    for kind in ("short", "verbatim", "tap"):
        print(f"  {kind:9} {kinds[kind]:5}  {kinds[kind] / total:6.1%}")
    for label, secs in (("all said", said), ("verbatim", [s for _, k, _, s in results if k == "verbatim"]),
                        ("short", [s for _, k, _, s in results if k == "short"])):
        if secs:
            q = statistics.quantiles(secs, n=10) if len(secs) > 1 else [secs[0]] * 9
            print(f"  {label:9} median {statistics.median(secs):5.1f} s  p90 {q[8]:5.1f} s  max {max(secs):6.1f} s  "
                  f"over 12 s {sum(s > 12 for s in secs) / len(secs):6.1%}")
    by_program = Counter(first_program(r["command"]) for r, k, _, _ in results if k == "verbatim")
    print("  verbatim by first program:", ", ".join(f"{p} {n}" for p, n in by_program.most_common(15)))
    by_source = Counter((r["source"], k) for r, k, _, _ in results)
    for source in sorted({r["source"] for r, _, _, _ in results}):
        n = sum(v for (s, _), v in by_source.items() if s == source)
        print(f"  {source:10} {n:5}  verbatim {by_source[(source, 'verbatim')] / n:6.1%}")
    if args.list:
        for row, kind, text, secs in results:
            if kind == args.list:
                print(f"{secs:6.1f}  {row['command'][:110]!r}\n        -> {(text or '')[:150]}")


if __name__ == "__main__":
    main()
