# Pointe: instructions for agents

Pointe is a voice call into coding-agent sessions: a Python daemon on a person's Mac, with their vendor keys in the
Keychain, their microphone, and the power to approve their agents' permission prompts. Strangers install it as a Claude
Code plugin. Every change ships to those machines; treat it that way. `AGENTS.md` is a symlink to this file.
`CONTRIBUTING.md` holds the contributor rules (DCO, synthetic data, benchmarks), `SECURITY.md` the threat model; this
file adds what an agent editing the repository must do.

## Working here

- Branch from `main`. One worktree per task, under `../claude-voice-wt/<name>`:
  `git worktree add ../claude-voice-wt/<name> -b <name> main`. Work and write only inside it.
- Tests (CONTRIBUTING.md, "How to test"): after each edit run `tools/test-changed`, the tests the change can break, not
  the full suite. Push without waiting for CI; CI runs every test (`--runslow`, all cores) on each push. If `main` is
  red, stop and fix it before anything else lands. The full gate runs at a release (`docs/releasing.md`).
  `tests/e2e/` calls paid vendors and starts real sessions: only when asked.
- Never run a test that opens windows on this Mac: the Mac smoke, the XCUITests, the iPhone UI tests in the Simulator,
  or `xcodebuild test` on a UI test target. A person is working at it. They refuse without `POINTE_UI_LOCAL=1`
  (`tools/ui_guard.py`), which only the owner sets. Push and read the `ui` workflow's run and artifacts instead.
- Never start, stop or talk to the live daemon (port 7860) and never read or write `~/.claude-voice`. Tests get a
  throwaway state dir from `tests/conftest.py` and use other ports; keep it so.
- Commits: `git commit -s` (DCO; `dco.yml` fails a pull request without it). Subjects in plain prose, like the log.
- `tests/`, `bench/`, `evals/` and docs hold synthetic data only: invented names, companies, paths, transcripts, keys.
  Nothing from a real session, no personal data, nothing Ballerine-internal.
- A rule the bot must follow lives in code with a test (`pointe/guards.py`, `pointe/daemon.py`), never only in a prompt. A bug fix
  starts with the failing test.
- Secrets reach only the one process that needs them, from the Keychain or its environment: never a file, a commit, a
  log, a fixture, a command line, or this conversation.

## Supply chain

`docs/security/supply-chain.md` is the inventory; `tests/test_supply_chain.py` enforces it. Run
`uv run --locked pytest -q tests/test_supply_chain.py` before any pull request that touches `pyproject.toml`,
`uv.lock`, `.github/`, `bin/`, `hooks/`, `plugin/`, `channel/`, `pointe/assets.py` or anything that downloads.

- **No new dependency without the owner's yes.** Ask first: the package, its license, what it pulls in, and why nothing
  already here does the job. Then `pyproject.toml`, `uv lock`, one line per new package (transitive ones too) in
  `docs/security/dependencies-allowlist.txt` with a reason, and a row in `THIRD_PARTY.md`. The test fails until the
  lockfile and the allowlist agree.
- **Lockfile only.** `uv run --locked`, `uv sync --locked`, `uv lock --check`. Never `pip install`, `uv pip install`,
  `uvx <tool>` without `@version`, or `uv run` / `uv sync` without `--locked` (`--no-sync` right after a locked sync is
  fine). Dependencies for another environment (the node, the text-model server) are dependency groups in the same lock.
- **A lockfile diff is review material.** Summarise it in the pull request: which versions moved, what was added or
  removed, and why.
- **Every download carries a pin.** A file by its SHA-256, a Hugging Face repository by a commit, both in `pointe/assets.py`,
  fetched only through `assets.fetch` / `assets.snapshot`. Never a bare `snapshot_download`, a repository at `main`, or a
  URL fetched and used by name alone. Add the host to `docs/security/egress-allowlist.txt`, the row to `THIRD_PARTY.md`
  and the table in `docs/security/supply-chain.md`.
- **No new outbound host** without a line and a reason in `docs/security/egress-allowlist.txt`; a host only shown to a
  person is a `link` line. The test greps every URL literal in the source, and checks the hosts a dependency was seen
  to contact at runtime (`tests/fixtures/dependency_hosts.txt`): add one there when a new dependency's log shows it.
- **GitHub Actions by 40-hex commit**, with a `# vX.Y.Z` comment, `permissions: contents: read`, and only the actions
  already in use unless the owner agrees. The SHA is the commit that tag points to, never the tag object's own: after
  changing a `uses:` line run `python3 tools/check_action_pins.py --write` and commit `tests/fixtures/action_pins.json`. uv's version is pinned in `bin/install-uv`, CI and the e2e images together;
  move all three at once.
- **Never pipe a download into a shell** (`curl … | sh`, `wget … | sh`), `eval` fetched text, or run a script by URL.
  The one installer, `bin/install-uv`, fetches to a file and checks its SHA-256 first.
- **Telemetry stays off.** A module that can load onnxruntime imports `no_telemetry` first (tested); nothing phones home.
- Dependabot's weekly pull requests are reviewed like any other: read the lockfile diff, run the gate, then merge.
