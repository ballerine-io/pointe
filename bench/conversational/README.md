# Pointe Conversational Coding Benchmarks

Five benchmarks of what a voice layer costs a coding agent. The agent is held fixed (`claude-haiku-5-5` in Claude Code)
and the same tasks reach it typed or spoken, so a score is the loss the voice interface adds. Pointe is the system under
test; every reference arm (keyboard, LLM router, keyword rules, null) was written by Pointe's team. Synthetic speech
only. Results and limits: [docs/benchmarks/](../../docs/benchmarks/README.md).

| Folder | Benchmark | Its harness README |
|---|---|---|
| `hlk/` | Humanity's Last Keystroke (HLK), the flagship: small coding tasks finished by voice only | [hlk/README.md](hlk/README.md) |
| `identifiers/` | Spoken Identifiers: does a spoken symbol reach the right symbol | [identifiers/README.md](identifiers/README.md) |
| `actions/` | Spoken Actions and False Approval: speech to harness actions, and approvals by a non-yes | [actions/README.md](actions/README.md) |
| `routing/` | Session Routing: four live sessions, one spoken request | [routing/README.md](routing/README.md) |
| `bargein/` | Barge-in and Time to a Correct Answer | [bargein/README.md](bargein/README.md) |

Each folder is self-contained: its `run.py`, `core/`, `adapters/`, items, `FROZEN.json` and `results/` are the ones its
published run used, so its tables regenerate byte for byte from its committed rows. The five harnesses share a design
but not code; a fix in one is not a fix in the others.

- To measure your own harness, write an adapter in one benchmark's `adapters/` and run that benchmark: the page for it
  in `docs/benchmarks/` gives the commands and the file to register the adapter in.
- `publish.py` writes `docs/benchmarks/` (but `hlk.md`, which HLK's own report writes) and
  `site/pointe/benchmarks/index.html` from the five results; `tests/test_conversational_publish.py` fails if a page
  differs from what it writes.
- Offline tests: `tests/test_conversational_<benchmark>.py`, in the repository's four-minute suite. `tests/conv_suite.py`
  lets one pytest process import the four harnesses that use the same module names.
