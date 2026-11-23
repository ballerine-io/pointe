# Pointe Conversational Coding Benchmarks

A reproducible self-evaluation harness with an adapter interface: one system under test (Pointe) and reference arms
the same team wrote, on synthetic speech. Not a leaderboard.

This branch carries the shared core and one benchmark, **Session Routing** (`routing/`, see its README). The other
benchmarks of the suite are built on their own branches against the same layout.

```
run.py                 the one command: routing | corpus | verify | freeze | report
core/                  adapter interface, agent sessions, corpus (Kokoro), ears (Soniox), ledger, stats, scrub, user
adapters/              pointe, llm_router (+ prompt), naive, keyboard, null, echo (offline tests only)
routing/               fixture, conversations.toml, check.py, runner.py, report.py, RESULTS.md
prices.json            list prices used for computed spend, with the date read
CANARY                 one GUID line, repeated in every item file
FROZEN.json            Pointe commit, router prompt, dataset and seed fixed before the first paid row
results/<run-id>/      rows.jsonl, events.jsonl, spend.jsonl, run.json, results.json, pointe-logs/
results/ledger.jsonl   every launch of this branch, smoke and preflight included
```

**Adding an adapter:** subclass `core.adapter.AgentArm` (it starts the four sessions the same way for everyone),
implement `utter(clip_id, pcm48)` for audio or `typed(text, sessions)` for text, report `delivered` and `asked` events,
and register it in `run.py`'s `make_arm`. A better `llm_router_prompt.txt` is welcome as a pull request.

No new dependency: the standard library, numpy, websockets, the Anthropic SDK and the `local` extra already locked.
Licenses: code MIT, text CC BY 4.0, audio Kokoro-82M (Apache-2.0), rebuilt by `run.py corpus`.
