# Spoken Actions and False Approval: its harness

A reproducible self-evaluation harness with an adapter interface: one system under test (Pointe) and reference arms
written by the same team, on synthetic speech. Not a leaderboard. The agent behind every arm is held fixed
(`claude --model claude-haiku-5-5` in a pty, one launch line), so the benchmarks measure what the voice interface adds
or loses, not agent strength.

This folder holds one benchmark of the suite (`../README.md`), with the harness it was run with: [`actions`](actions/README.md): Spoken Actions and False Approval.

## Layout

```
run.py                one command: corpus | verify | actions | report
core/adapter.py       the adapter interface and normalized events
core/agent.py         interactive Claude Code in a pty (fresh config, logging hooks, transcript parsing), and a fake agent
core/corpus.py        Kokoro rendering, seeded truncation, audio.lock
core/ears.py          Soniox real-time, the recognizer of the llm-router and naive arms
core/ledger.py        the spend ledger and the gate before every launch
core/stats.py         Wilson intervals, flip rate
core/scrub.py         refuses home paths, key-shaped text and absolute paths outside /tmp in anything committed
core/report.py        rows -> results.json and the generated results page
adapters/             keyboard, null, naive, llm_router (+ its public prompt), pointe, echo (offline tests)
actions/              items.toml, fixture/, check.py, protocol.py, README.md, RESULTS.md (generated)
prices.json           list prices used for computed spend, with the date read and the source
voices.toml           the voice panel and its license
CANARY                one GUID line, repeated in every item file
FROZEN.json           commits and hashes fixed before the first paid row
results/<run-id>/     rows.jsonl, run.json, results.json
results/ledger.jsonl  every paid launch, smoke and debug included
```

## Adding an adapter

Subclass `core.adapter.Adapter`: declare `capabilities`, and implement `say(pcm, rate, item)` (play the 16 kHz clip at
real-time pace and act), optionally `ready()` (when your harness is ready to listen), `spend()` and `versions()`. The
base class owns the agent session, so every arm drives the same pty with the same launch line; only `extra_args` may
add flags (Pointe's `--plugin-dir`). Register it in `run.py`'s `adapter_for`. `run.py verify` runs the offline checks.

## Licenses

Text (utterances, instructions, fixtures) CC BY 4.0, all invented. Code MIT, like the repository. Audio is rendered by
Kokoro-82M (Apache-2.0) at the commit pinned in `assets.py`; no recording of any person is used.
