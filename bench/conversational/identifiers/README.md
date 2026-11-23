# Pointe Conversational Coding Benchmarks

A reproducible self-evaluation harness with an adapter interface: one system under test (Pointe) and reference arms
written by the same team, on synthetic speech. Not a leaderboard. Design: revision 2 of the suite design (sections 3
to 5). This build carries the shared core and the first benchmark, `identifiers` (Spoken Identifiers); the others
(`hlk`, `actions`, `routing`, `bargein`) plug into the same `core/` and `adapters/`.

## Run it

```
uv run --locked python bench/conversational/identifiers/run.py verify                                   # offline, $0
uv run --locked --extra local python -I bench/conversational/identifiers/run.py corpus                  # render the audio, $0
uv run --locked python bench/conversational/identifiers/run.py identifiers --budget-usd 12 --dry-run     # the plan and its cost
uv run --locked python bench/conversational/identifiers/run.py identifiers --budget-usd 12 [--adapter pointe,llm-router] [--smoke]
uv run --locked python bench/conversational/identifiers/run.py report <run-id>                          # rows -> summary
uv run --locked pytest -q tests/test_conversational_identifiers.py                          # offline tests
```

Keys come from the environment (`ANTHROPIC_API_KEY`, `SONIOX_API_KEY`) or the macOS Keychain under the names Pointe
uses, and go only into the one child process that needs them. The Pointe arm's daemon reads its own keys, as it does
for a user. Ports: `--port-base` (default 9400; each worker uses base + 1 + worker, its Pointe daemon that port and
that port + 50); 7860 and 7443 are refused. Everything a run creates lives in `/tmp/pccb/<run-id>/`.

## Layout

- `core/`: `adapter.py` (interface, events), `agent.py` (the one launch line in a pty, the fresh config folder, the
  preflight), `runner.py` (workers, ports, budget gate, the Pointe checkout under test), `corpus.py` (Kokoro, babble,
  audio.lock), `ears.py` (the recognizer of `naive` and `llm-router`), `ledger.py`, `stats.py`, `audit.py`,
  `scrub.py`, `user.py` (question detector), `keys.py`.
- `adapters/`: `keyboard` (two arms: canonical and transcript), `null`, `naive`, `llm_router` (+ its published
  prompt), `pointe` (+ `pointe-text`), `echo` (offline tests).
- `identifiers/`: `fixture/` (the invented almanac repo), `items.toml`, `check.py`, `bench.py`, `report.py`,
  `audio.lock`, `README.md`.
- `results/<run-id>/`: `rows.jsonl`, `spend.jsonl`, `run.json`, `logs/` (scrubbed events, tool uses, Pointe's log
  lines), `summary.json`, `summary.md`. `results/ledger.jsonl`: every paid launch, smoke and preflight included.
- `FROZEN.json`: the Pointe commit, the router prompt's commit and hash, the item seed and the Claude Code version,
  committed before the first non-smoke paid row. `CANARY`: one GUID, repeated in every item file.

## Add an adapter

Implement `core.adapter.Adapter` (start, say, type, key, events, speech, versions, spend, stop), name its
capabilities, and add it to the benchmark's `make_adapter`. An item that needs a capability the adapter lacks is
`unsupported` and shown as coverage, never as a failure. A better `llm_router_prompt.txt` is welcome as a pull request.

## Licenses

Text (items, utterances): CC BY 4.0. Code: MIT, like the repository. Speech: Kokoro-82M v1.0 (Apache-2.0), voices
`af_heart`, `am_michael`, `bf_emma`, `bm_george`, rendered locally from the files pinned in `assets.py`. No recorded
human speech, no cloud voice, no microphone.

## Limits

Synthetic speech in four clean US and British voices is easier than real users and favours Pointe, whose local voice
is Kokoro. Every reference arm is written by Pointe's team, who know Pointe's internals. The agent is fixed
(`claude-haiku-5-5`) so the tasks are small. Spend from interactive sessions is computed from transcript usage and
`prices.json`, and Pointe's own spend from its log (see `adapters/pointe.py`); neither is a vendor bill.
