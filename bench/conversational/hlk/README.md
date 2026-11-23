# Humanity's Last Keystroke: its harness

A reproducible self-evaluation harness with an adapter interface: audio in, coding-agent actions on a repository,
speech out. The coding agent is held fixed, so a score is the loss the voice interface adds. One system under test
(Pointe) and reference arms written by the same team, on synthetic speech. Not a ranking of products.

This folder holds the flagship of the suite (`../README.md`), **Humanity's Last Keystroke (HLK)**, with the harness it was run with: a pilot voice-only coding
benchmark, v0.1, synthetic speech, n = 36 in 12 families. See `hlk/README.md` and the results page,
`docs/benchmarks/hlk.md`.

## Run it

```
uv sync --locked --extra local                                           # Kokoro and Whisper, already pinned in assets.py
uv run --locked python bench/conversational/hlk/run.py corpus                # render the synthetic speech, $0
uv run --locked python bench/conversational/hlk/run.py verify                # offline checks, $0, no keys
HLK_POINTE_CHECKOUT=<a Pointe checkout at the commit under test> \
uv run --locked python bench/conversational/hlk/run.py hlk --budget-usd 55 --port-base 9300 --workers 3
uv run --locked python bench/conversational/hlk/run.py report                # rows -> docs and site page
```

`--dry-run` prints the plan and its planning estimate and spends nothing. `--smoke` runs 2 items, never published.
`--debug` runs any `--items` for adapter work; its spend goes to the ledger as debug. Paid runs refuse to start until
`FROZEN.json` (written by `run.py freeze`) is committed, and refuse a Pointe checkout at another commit.

Keys: the agent's Anthropic key, and the Soniox and Anthropic keys of the reference arms' own calls, come from the
environment or the macOS Keychain and go only to the one process (or call) that needs them. The Pointe daemon reads its
own. Nothing here prints, logs or commits a key; `core/scrub.py` refuses a row with a home path or key-shaped text.

## Layout

- `run.py`: the one command. `core/`: adapter interface and launch line (`adapter.py`), runner and budget gate
  (`runner.py`), scripted user and question detector (`user.py`, `detector.py`), speech corpus (`corpus.py`),
  recognizers (`asr.py`), ledger, statistics, transcript audit, scrubber, report, verify.
- `adapters/`: `keyboard` (canonical and transcript), `null`, `naive` ("keyword rules, ours"), `llm_router` with its
  published prompt, `pointe`, `echo` (offline tests only).
- `hlk/`: the twelve families, the scorer, `CONTRIBUTING.md`, `audio.lock`.
- `results/<run-id>/`: `rows.jsonl`, `events.jsonl`, `spend.jsonl`, `run.json`, and for a published run `final.jsonl`
  (the files each run left changed, written by `run.py finals --rerun-faults <run-id>`; `run.py verify` re-scores every
  row from them); `results/ledger.jsonl` holds every paid launch, smoke and debug included.

## Add an adapter

Implement the interface in `core/adapter.py` (`start`, `say`, `type`, `key`, `events`, `speech`, `versions`, `spend`,
`stop`, and `capabilities`), start the agent with the shared launch line (`adapters/base.py` does), and register it in
`core/runner.make_adapter`. An item that needs a capability the adapter lacks is shown as coverage, never as a failure.

## Isolation

Every agent runs in its own `/tmp/pccb/<run>/<item>` repository with a fresh `CLAUDE_CONFIG_DIR`; `HOME` is untouched.
The Pointe arm runs its own daemon with `CLAUDE_VOICE_STATE` under `/tmp/pccb-pointe/`, ports from `--port-base` (never
7860 or 7443), `POINTE_LINK_DIR` under that state (so the installed `pointe` command is never rewritten), and a guard
folder first on the daemon's `PATH` that refuses `open`, `osascript`, `codex` and `opencode` (a voice-started session
would open a terminal window; the other harnesses reach live shared services). No Chrome, no GUI app, no microphone.

## Licenses

Text and tasks CC BY 4.0. Code MIT, like the repository. Speech: Kokoro-82M v1.0 (Apache-2.0), rendered locally.
