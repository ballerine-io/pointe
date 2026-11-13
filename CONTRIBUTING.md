# Contributing

```
git clone <this repo> && cd pointe
bin/voice-doctor                                 # what runs here, and what is missing
uv run --locked pytest -q tests/ --ignore=tests/e2e
```

These run in about a minute and a half, with no keys and no cost; tests that call vendors (RUN_LIVE=1) or need Apple
silicon or the local extra skip themselves. CI runs the same command on Ubuntu.

## Before you change behavior

- **Rules live in code.** If the bot must never do something, enforce it in `guards.py` or `daemon.py` and add a test. A
  sentence in a prompt is not a guarantee.
- **Bug fix: failing test first.** `tests/test_orchestrator.py` drives the real daemon code with a fake model.
- **Prompt or model change: run the benchmark.** `bench/brain_bench.py` compares against saved results. Scores move, and
  a change that reads better can score worse.
- **Audio paths: run `tests/e2e/run_all.sh`.** It calls paid APIs and starts real Claude Code sessions on isolated ports.

## Adding a vendor

Add it to `KEYS` and the role orders in `vendors.py`, add its text and step adapters, then add a row to
`bench/results/combinations.md` with what you measured. A role order changes only with a benchmark behind it.

## Test data

Everything in `bench/`, `evals/` and `tests/` must be synthetic: invented companies, names and paths. Never a real session.

## Sign your commits (DCO)

Every commit needs a `Signed-off-by:` line: `git commit -s` adds it. By signing, you certify the
[Developer Certificate of Origin](https://developercertificate.org/): you wrote the change, or have the right to submit
it under this project's MIT license. A check on each pull request fails if a commit is not signed. To sign commits you
already made: `git rebase --signoff main`, then push again.

Changes reach `main` only through a pull request that a maintainer approves.
