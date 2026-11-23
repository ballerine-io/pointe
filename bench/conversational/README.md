# Pointe Conversational Coding Benchmarks

One runner (`run.py`), one adapter interface (`core/adapter.py`), one synthetic speech corpus builder
(`core/corpus.py`, Kokoro-82M) and one results format, per the design (revision 2). This branch holds the shared core
and the `bargein` benchmark: see [bargein/README.md](bargein/README.md) and [bargein/RESULTS.md](bargein/RESULTS.md).

## Add an adapter

Implement the `Adapter` protocol in `core/adapter.py` (start, say, type, key, events, speech, versions, spend, stop)
in `adapters/<name>.py`, register it in `bargein/bench.py:make_adapter`, and run with `--adapter <name>`. Start the
agent through `adapters/base.py` (the shared launch line) so the comparison stays on equal terms. Record your spend
as `SpendRow`s; the runner gates every launch on the ledger (`results/ledger.jsonl`).

## Layout

`core/` (agent launch and preflight, runner helpers, ledger, statistics, audio, scrub), `adapters/` (keyboard, null,
naive, llm-router and its prompt, pointe, echo for the offline tests), `bargein/` (fixtures, items, check, facts,
report), `results/<run-id>/` (rows, events, spend, run.json, results.json), `voices.toml`, `prices.json`, `CANARY`,
`FROZEN.json`. Offline tests: `tests/test_conversational_bargein.py`.
