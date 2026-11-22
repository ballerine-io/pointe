"""Write the setups table from setups.py: docs/setups.md whole, and the short table in README.md and /pointe:setup.

    python3 tools/setups.py           write them
    python3 tools/setups.py --check   exit 1 if any is not what this would write (tests/test_setups.py runs it)

Standard library only.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import setups  # noqa: E402

OUT = "docs/setups.md"
START, END = "<!-- setups: written by tools/setups.py from setups.py -->", "<!-- end setups -->"
BLOCKS = ("README.md", "plugin/commands/setup.md")


def page() -> str:
    roles = "\n".join(f"- **{role}**: {words}" for role, words in setups.ROLES.items())
    return f"""# Setups: which keys Pointe needs, and for what

Written by `tools/setups.py` from `setups.py`: edit those, not this file.

{setups.WHY_KEYS}

Pointe has five roles. Each setup fills all five, with the keys in its row:

{roles}

{setups.table(full=True)}

{setups.BUSY_HOUR} "Measured" is the real audio suite (`tests/e2e/run_all.sh`, 35 checks: 19 single-session, 12
multi-session, 4 echo), one run per setup on 2026-11-13 with only that setup's keys visible, and the per-role benchmarks
in `bench/`. "Not measured" means no run covered it. Voices are synthetic; no setup was measured on a real human call.

No setup is best on every axis. The fastest and most accurate voice has the highest whole-setup result and the best ears
and voice, but its brain (Sonnet) and the Free start's brain (Gemini) are within the margin of each other: Gemini passed
more cases, Sonnet answered faster. Pick by what matters to you:

{chr(10).join(f"- **{s.pick_for[0].upper() + s.pick_for[1:]}**: {s.name} (`pointe setup {s.id}`)" for s in setups.SETUPS)}

With nothing chosen, `/pointe:setup` recommends **{setups.BY_ID[setups.DEFAULT].name}**: one key, working in two minutes.

## Choosing and switching

`pointe setup` shows this table and the setup in use; `pointe setup <id>` switches, and from then on the daemon uses
exactly that setup's vendors, whatever other keys the Keychain holds. `pointe key <vendor>` saves a key through a Mac
window, `pointe key check <vendor>` tries it with one tiny live call. Restart the voice (`/pointe:stop`, then
`/pointe:voice`) to use a new setup or key. The Mac app's Settings, Model keys, does the same with a menu, and the page's
Settings shows the setup in use and each key as In use, Needed or Optional.
"""


def block(path: str) -> str:
    return f"{START}\n{setups.table(full=False)}\n\nSources, speed and where your words go: [docs/setups.md]" \
           f"({'../../' if path.startswith('plugin/') else ''}docs/setups.md).\n{END}"


def _with_block(path: str, text: str) -> str:
    inner = block(path)
    if START not in text:
        raise ValueError(f"{path}: no {START} marker")
    return re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: inner, text, flags=re.S)


def main(argv: list[str]) -> int:
    wanted = {OUT: page()}
    for path in BLOCKS:
        wanted[path] = _with_block(path, (ROOT / path).read_text())
    stale = [p for p, text in wanted.items() if not (ROOT / p).exists() or (ROOT / p).read_text() != text]
    if "--check" in argv:
        if stale:
            print(f"stale: {', '.join(stale)}: run python3 tools/setups.py", file=sys.stderr)
            return 1
        return 0
    for p in stale:
        (ROOT / p).write_text(wanted[p])
    print(f"wrote {', '.join(stale) or 'nothing: all current'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
