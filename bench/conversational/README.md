# Pointe Voice Coding Benchmarks: the harnesses

Each folder here is one benchmark with its own harness, items, results and ledger. The published results come from one
tagged release at a time: [docs/benchmarks/README.md](../../docs/benchmarks/README.md), with the rows in
`bench/results/<date>-<tag>/`. Pointe's team wrote every harness and every reference arm. Most speech is synthetic.

| Folder | Benchmark | Status |
|---|---|---|
| `dialogues/` | The conversation suite (45 scripted dialogues, Pointe against a plain router) and the recorded yes/no/stop/mm-hm dialogues | Published for 0.8.5 |
| `hlk/` | Humanity's Last Keystroke (HLK): small coding tasks finished by voice only | Published for 0.8.5 (freeze in `hlk/FROZEN.json`) |
| `identifiers/` | Spoken Identifiers | Withdrawn 2026-11-25; not re-run |
| `actions/` | Spoken Actions and False Approval | Withdrawn 2026-11-25; not re-run |
| `routing/` | Session Routing | Withdrawn 2026-11-25; not re-run |
| `bargein/` | Barge-in and Time to a Correct Answer | Withdrawn 2026-11-25; not re-run |

The four withdrawn benchmarks ran on 2026-11-23 on a Pointe build that is not public, and an integrity audit found
faults in each (listed in [docs/benchmarks/withdrawn/2026-11-23/](../../docs/benchmarks/withdrawn/2026-11-23/README.md)).
Their harnesses and rows stay here as they were; their scorers are not fixed, so do not cite numbers they print.

- To measure your own harness, write an adapter in a benchmark's `adapters/` and run that benchmark; its README gives
  the commands. The budget gate counts that benchmark's whole ledger, so pass the ledger's total plus your run.
- Offline tests: `tests/test_conversational_<benchmark>.py` and `tests/test_dialogue_score.py`. `tests/conv_suite.py`
  lets one pytest process import the harnesses that use the same module names.
