# Contributing

Pointe is a conversational layer for your coding agents. It is MIT
licensed and community-supported. Pull requests, bug reports, test reports from machines we do not have, and ideas are
all welcome. What may come next, sorted by votes: [ROADMAP.md](ROADMAP.md). Teams that use Pointe in real work can join
the [Conversational Engineering Working Group](#the-conversational-engineering-working-group).

## Your first pull request in 15 minutes

You need git and a Mac or a Linux machine. No keys and no cost, until step 4.

1. **Clone, and install uv** (pinned, checked against its SHA-256; it does nothing if uv is already there):

   ```
   git clone https://github.com/ballerine-io/pointe.git && cd pointe
   bin/install-uv
   ```

2. **See what runs here.** `bin/voice-doctor` downloads Python and the locked packages on its first run (about 190 MB),
   then says which keys and tools it found.

3. **Run the offline suite.** About four minutes, no keys. Tests that call vendors (`RUN_LIVE=1`), or need Apple silicon
   or the local extra, skip themselves. CI runs the same command on Ubuntu.

   ```
   uv run --locked pytest -q tests/ --ignore=tests/e2e
   uv run --locked pytest -q tests/test_ui_page.py          # one file, while you work
   ```

4. **Run a daemon of your own**, on its own port and state folder, so it never touches a Pointe you use (port 7860,
   `~/.claude-voice`). It needs one model key, from the Keychain (`bin/pointe key gemini` opens a window for it) or
   from its environment variable; it refuses to start without one.

   ```
   export CLAUDE_VOICE_STATE="$(mktemp -d)" CLAUDE_VOICE_DAEMON_PORT=7870
   bin/voice-daemon ensure                                  # prints the page's address
   bin/voice-daemon stop
   ```

   Never put a key on a command line or in a file in the repository.

5. **Change one thing, test it, sign the commit, open the pull request.**

   ```
   git switch -c my-fix
   uv run --locked pytest -q tests/ --ignore=tests/e2e
   git commit -s -m "The sessions column keeps a long name on one line"
   ```

   Commit subjects are plain sentences, like the log. A maintainer reviews every pull request before it reaches `main`.

## Development setup

| You need | For | How |
|---|---|---|
| git, and a Mac or a Linux machine | everything | |
| uv | Python, the packages, every command below | `bin/install-uv` installs the pinned version, checked against its SHA-256 |
| Python 3.12 or newer | the daemon and the tests | uv installs it: `.python-version` names 3.12, `pyproject.toml` requires 3.12 or newer |
| The locked packages | the daemon and the tests | `uv sync --locked`; any `uv run --locked` syncs first |
| The local extra (Apple silicon) | local models: `pointe local`, the local benchmarks | `uv sync --locked --extra local` (about 290 MB to download) |
| Google Chrome | the page's tests (`tests/test_ui_page.py`, `tests/test_ui_layout.py`) and the end-to-end suites | They skip without it |
| Xcode 16 or newer, macOS 15 or newer | the Mac app, the iPhone app and PointeKit | Free in the App Store. The iPhone app targets iOS 18; its tests run in the iPhone Simulator |
| Node.js | channel mode only (`pointe start`) | |
| Model keys | only the live and end-to-end tests, and a daemon of your own | The macOS Keychain or the environment, never a file or a command line |

`bin/voice-doctor` says which of these it found.

## Repository layout

The daemon's modules are in `pointe/` (flat: they import each other by name and run as scripts, nothing is installed
as a package), the apps in `apps/`. This section is the one place in the docs that maps parts to paths: when files move,
update it here.

| Path | What it is |
|---|---|
| `pointe/daemon.py` | The hub: the HTTP routes, the call pipeline (ears, echo guard, brain, mouth), approvals, `/voice/status` |
| `pointe/brain.py` | Decides what to say. Speech is a tool call, so code checks a reply before anyone hears it |
| `pointe/guards.py`, `pointe/readout.py` | Rules in code: what can be read out, what counts as a plain yes, which routes the phone key may call |
| `pointe/brief.py` | The reader: session notes and reports |
| `pointe/harnesses/` | One adapter per agent (Claude Code, OpenCode, Codex), and `pointe/remote.py` for sessions on other machines. The contract: [docs/harnesses.md](docs/harnesses.md) |
| `pointe/sessions.py` | The registry of joined sessions, their transcripts, and sends |
| `pointe/vendors.py`, `pointe/setups.py`, `pointe/keys.py` | Each vendor, its key, the order roles pick them in; the six setups; `pointe key` |
| `pointe/pair.py`, `pointe/phone_pairing.py`, `pointe/remote.py`, `pointe/phone.py`, `pointe/calllink.py` | The phone listener, pairing, the phone's call and its wire format, and the link that keeps a call through a dropped connection |
| `pointe/node.py`, `pointe/nodelink.py`, `pointe/hub_nodes.py` | Other machines: the node, the link, and the hub's side of it ([docs/multi-machine.md](docs/multi-machine.md)) |
| The other `pointe/*.py` | One module per feature: `pointe/meeting.py`, `pointe/nightshift.py`, `pointe/briefing.py`, `pointe/drive.py`, `pointe/whisper.py`, `pointe/ptt.py`, `pointe/speaker.py` (the voice lock), `pointe/vocabulary.py`, and the rest |
| `pointe/ui.html` | The page: one file, no build step (`pointe/ui_*.html` are parts the daemon puts in it) |
| `apps/PointeKit` | The Swift package both apps share: `PointeKit` (wire format, loopback client), `PointeUI` (every screen), `PointeMacKit` (the Mac's own parts). Unit tests in `Tests/` |
| `apps/ios/` | The iPhone app: its entry point, intent and icon (`apps/ios/Pointe`), the Control and widget (`apps/ios/PointeWidget`), its tests (`PointeTests`, `PointeUITests`), and drivers against a test daemon (`apps/ios/e2e/`) |
| `apps/macos/` | The Mac app (`PointeMac`), its tests, `test.sh`, `build.sh`, and `tools/make_project.py`, which writes its Xcode project |
| `pointe/apps.py` | `pointe apps doctor`, `mac`, `ios`: builds, signs and installs the two apps from source. Standard library only, so it runs on Xcode's Python; tested against recorded tool output in `tests/test_apps.py` |
| `bin/`, `plugin/`, `hooks/`, `channel/`, `install.sh` | The launchers (`bin/pointe` and the scripts it runs), the installer for Pointe without Claude Code, the Claude Code commands (`/pointe:*`), the permission hook, and the channel for `pointe start` |
| `tests/` | The offline suite. `tests/e2e/` calls paid vendors and starts real sessions |
| `bench/`, `evals/` | Benchmarks and scenarios behind every default, all synthetic |
| `tools/` | Generators and checks: the setups table, the roadmap, the parity matrix, the site's version, the docs site (`build_docs.py`), the release tarball, and the demo-video recorder (`tools/demo-video/`) |
| `docs/` | These docs. `docs/design/` holds plans and reviews, `docs/security/` the supply-chain inventory and the security reviews |
| `site/` | The website, eng.ballerine.com. `site/pointe/roadmap/` and `site/pointe/docs/` are generated |

How the parts fit together: [docs/architecture.md](docs/architecture.md). How a call works, step by step:
[docs/how-it-works.md](docs/how-it-works.md). The threat model: [SECURITY.md](SECURITY.md).

## Running the tests

Every command runs from the top of the repository, with paths from the [layout](#repository-layout) above.

### The offline suite

No keys, no cost, about four minutes. CI runs the same command on Ubuntu, so a test that needs a Mac, Chrome, Apple
silicon or a key skips itself elsewhere.

```
uv run --locked pytest -q tests/ --ignore=tests/e2e        # all of it
uv run --locked pytest -q tests/test_ui_page.py            # one file
uv run --locked pytest -q tests/test_pair.py -k rotate     # the tests whose names match
```

Tests get a throwaway state folder and ports of their own (`tests/conftest.py`); none touches a Pointe you use.
`tests/test_orchestrator.py` drives the real daemon code with a fake model: start a bug fix there.

### The page

`tests/test_ui_page.py` and `tests/test_ui_layout.py` drive `pointe/ui.html` in a headless Chrome against a stub Mac
(`tests/page_rig.py`): a small server that serves the page as the daemon does and answers `/voice/status` from a fixture
the test changes. A test sets the fixture, waits for the page, and reads or clicks it. Words the page and the apps both
show are checked by `tests/test_copy_parity.py`, colours by `tests/test_theme.py`, and what each surface has by
`tests/test_parity_matrix.py`.

### The apps

```
(cd apps/PointeKit && swift test)    # PointeKit: every screen, the call, the models; on the Mac
apps/macos/test.sh unit                    # PointeKit and the Mac app's unit tests: what CI runs
```

**Tests that open windows run in CI, not on your Mac.** The Mac smoke (`apps/macos/test.sh smoke`,
`apps/macos/e2e/smoke.py`), the Mac app's XCUITests (`apps/macos/test.sh ui`), the live test (`apps/macos/e2e/live.py`),
and every driver of the iPhone UI tests (`apps/ios/e2e/*.py`, `tests/e2e/ios_app.py`, `tests/e2e/ios_phone_pair.py`,
`tools/demo-video/capture.py` with the iPhone) put windows on the screen and take the keyboard, so nobody can work at
that Mac while they run. Each one refuses to start unless `CI=true` (GitHub Actions sets it) or you set
`POINTE_UI_LOCAL=1` yourself, and says so in one line (`tools/ui_guard.py`, tested by `tests/test_ui_guard.py`). An
agent never sets `POINTE_UI_LOCAL`: it pushes and reads the run.

```
POINTE_UI_LOCAL=1 apps/macos/test.sh smoke # every main flow on invented sessions, through the Accessibility API
POINTE_UI_LOCAL=1 apps/macos/test.sh ui    # the same flows with XCUITest; macOS asks you to allow UI automation first
```

The iPhone app's tests run in the iPhone Simulator, as in CI (`.github/workflows/test.yml`, job `ios`): pick an
available simulator's id from `xcrun simctl list devices available`, then

```
(cd ios && xcodebuild test -project Pointe.xcodeproj -scheme Pointe -destination "id=<simulator id>" \
  -only-testing:PointeTests CODE_SIGNING_ALLOWED=NO -quiet)
(cd apps/PointeKit && xcodebuild test -scheme PointeKit-Package -destination "id=<simulator id>" \
  -only-testing:PointeUIUnitTests -quiet)
```

The UI tests (`apps/ios/PointeUITests`) and the drivers in `apps/ios/e2e/` run the app against a test daemon; each driver's first
lines give its command, with its own state folder and ports. `POINTE_UI_LOCAL=1 uv run --locked python -I
apps/macos/e2e/live.py` runs the real Mac app against its own daemon, with keys and the microphone.

### End to end, with paid vendors

`tests/e2e/` starts real Claude Code sessions and calls the vendors on your keys, so each run costs money; the cost of
a run is not recorded. Run them when you change the audio path, or ask a maintainer to.

```
tests/e2e/run_all.sh    # three suites in parallel, each on its own daemon, port and sample repository
```

`run_all.sh` runs `scenarios.py brain` (one session), `multi_session.py` (routing, switching, permissions) and `pointe/echo.py`
(the bot's voice leaking into the microphone) on ports 7862 to 7864, with state in `/tmp/cv-state-*`, and stops a suite
after 25 minutes. To run one suite by itself, give it a state folder and a port of its own:

```
export CLAUDE_VOICE_STATE="$(mktemp -d)" CLAUDE_VOICE_DAEMON_PORT=7861
uv run --locked python -I tests/e2e/scenarios.py brain        # one session, about 15 minutes
uv run --locked python -I tests/e2e/multi_session.py          # two sessions
ECHO_GAIN=0.9 uv run --locked python -I tests/e2e/echo.py     # speakers leaking into the microphone, no echo cancel
```

`evals/sim.py` runs a whole call on the real voice model, without audio, from synthetic scenarios: each run calls the
Gemini API at a small cost ([evals/README.md](evals/README.md)).

### Benchmarks

Every default comes from a benchmark in `bench/`, on synthetic data. Each runner says its commands in its first
lines; for example:

```
uv run --locked python -I bench/brain_bench.py validate       # the cases: counts, lengths, synthetic-data lint; free
uv run --locked python -I bench/brain_bench.py run --role brain
uv run --locked python -I bench/brain_bench.py report         # writes bench/results/brain.md
```

The others measure the ears (`stt_bench.py`), the voice (`tts_bench.py`, `local_tts_bench.py`), the voice lock
(`speaker_bench.py`), the vocabulary (`vocab_bench.py`) and whisper mode (`whisper_bench.py`); their results are in
`bench/results/`. The five conversational engineering benchmarks are in `bench/conversational/`, each with a spend cap
(`--budget-usd`) checked before every launch, and their spend per run is in
[docs/benchmarks/README.md](docs/benchmarks/README.md#spend).

### Before a pull request

```
uv run --locked pytest -q tests/test_supply_chain.py       # when you touch dependencies, workflows, bin/, hooks/, plugin/ or downloads
uv run --locked python tools/build_docs.py                 # after a change to docs/: writes the docs pages on the site
```

## Pick something to work on

- [**good first issue**](https://github.com/ballerine-io/pointe/issues?q=is%3Aopen+label%3A%22good+first+issue%22):
  small, with the files named and a "done when". Some are reports that need no code, such as a real call on Linux.
- [**help wanted**](https://github.com/ballerine-io/pointe/issues?q=is%3Aopen+label%3A%22help+wanted%22): larger, or
  needs a machine or a skill the maintainers do not have.
- [**roadmap**](ROADMAP.md): the bigger items, sorted by 👍. Comment on the issue before you start one, so the approach
  is agreed before you write much code.

The `area/` labels say which part of the code an issue touches, and `platform/` which operating system.

## Propose something

- **A feature:** start in [Discussions → Ideas](https://github.com/ballerine-io/pointe/discussions/categories/ideas).
  Ideas that gather support become roadmap issues. Pointe's rule: a feature may only narrow what a spoken word can
  approve or send, never widen it.
- **A new agent (harness):** the harness request form in [issues](https://github.com/ballerine-io/pointe/issues/new/choose).
- **A bug:** the bug report form, with the output of `bin/pointe doctor`. Check every line before you paste it.
- **A question:** [Discussions → Q&A](https://github.com/ballerine-io/pointe/discussions/categories/q-a).
- **A vulnerability:** never in public. [SECURITY.md](SECURITY.md) says how to report it privately.

## Before you change behavior

- **Rules live in code.** If the bot must never do something, enforce it in `pointe/guards.py` or `pointe/daemon.py` and add a test. A
  sentence in a prompt is not a guarantee.
- **Bug fix: failing test first.** `tests/test_orchestrator.py` drives the real daemon code with a fake model.
- **The page:** `tests/test_ui_page.py` and `tests/test_ui_layout.py` drive `pointe/ui.html` in a headless Chrome against a stub
  Mac (`tests/page_rig.py`). Words the page and the app both show live in shared dictionaries that
  `tests/test_copy_parity.py` checks; colours come from `assets/theme.json` (`tests/test_theme.py`).
- **The iPhone app:** add to `apps/PointeKit/Tests/PointeUIUnitTests`; CI builds the app and runs them on a simulator.
- **Prompt or model change: run the benchmark.** `bench/brain_bench.py` compares against saved results. Scores move, and
  a change that reads better can score worse.
- **Audio paths: run `tests/e2e/run_all.sh`.** It calls paid APIs and starts real Claude Code sessions on isolated ports.
  If you have no keys, say so in the pull request and a maintainer runs it.

## New dependencies and downloads

The supply-chain rules are in [CLAUDE.md](CLAUDE.md) ("Supply chain") and enforced by `tests/test_supply_chain.py`.
In short:

- **No new dependency without the owner's yes.** Ask in the issue first: the package, its license, what it pulls in, and
  why nothing already here does the job. The iPhone app uses no packages at all.
- **Lockfile only:** `uv run --locked` and `uv sync --locked`. Nothing is installed around the lockfile.
- **Every download is pinned** by SHA-256 or commit in `pointe/assets.py`, and every host the code can reach is listed in
  `docs/security/egress-allowlist.txt`. The page and the site load nothing from another host.

Run `uv run --locked pytest -q tests/test_supply_chain.py` before a pull request that touches `pyproject.toml`,
`uv.lock`, `.github/`, `bin/`, `hooks/`, `plugin/`, `channel/`, `pointe/assets.py` or anything that downloads.

## Adding a vendor

Add it to `KEYS` and the role orders in `pointe/vendors.py`, add its text and step adapters, then add a row to
`bench/results/combinations.md` with what you measured. A role order changes only with a benchmark behind it.

## Adding a harness

Follow "Adding a harness" in [docs/harnesses.md](docs/harnesses.md): subclass `Harness`, declare its capabilities
truthfully, and add a fake-service test like `tests/test_opencode.py` plus a case in `tests/test_mixed_harnesses.py`.

## Test data

Everything in `bench/`, `evals/` and `tests/` must be synthetic: invented companies, names and paths. Never a real session.

## Sign your commits (DCO)

Every commit needs a `Signed-off-by:` line: `git commit -s` adds it. By signing, you certify the
[Developer Certificate of Origin](https://developercertificate.org/): you wrote the change, or have the right to submit
it under this project's MIT license. A check on each pull request fails if a commit is not signed. To sign commits you
already made: `git rebase --signoff main`, then push again.

## Releases

A release is a version commit on `main`, an annotated tag, and a GitHub Release with notes a person can read. A change
to anything a user runs (the Python, `bin/`, `hooks/`, `plugin/`, the page, the apps) reaches them only with a new
version, because Claude Code installs the plugin from `main` and keeps one copy per version. Docs, tests, `bench/` and
the site's copy alone need none. Ask in your pull request whether it needs one; a maintainer cuts it. The version
commit moves the plugin manifest, `pyproject.toml` and `uv.lock`, both apps' projects, the changelog and the site
together, and `tests/test_version.py` fails when they disagree. The whole process: [docs/releasing.md](docs/releasing.md).

## Security reviews

Pointe holds your keys, hears your microphone and can approve your agents' permission prompts. A change to a security
boundary (the listeners and their authentication, pairing, what a spoken word or a tap can approve, how keys reach
processes, the install path) needs tests in `tests/test_security.py` or next to the code, and is covered by the
project's security reviews. Each review is published in `docs/security/reviews/`, with what was looked at, what was
found, and what was done about each finding; the cadence and the method are in that folder's `README.md`. A maintainer
checks each finding against the code before it is marked fixed, by design or accepted. The threat model is
[SECURITY.md](SECURITY.md). Report a vulnerability privately, never in an issue.

## The Conversational Engineering Working Group

Teams that use Pointe in real work. Members share what works and what breaks, help shape the practice, the roadmap and
the benchmarks (Humanity's Last Keystroke among them), and contribute code or adapters when they can. They get a voice
in the roadmap, early builds, a shared channel with the maintainers, and their team's name on the site if they want it.
There is no fee and no contract. To join, open the
[working group form](https://github.com/ballerine-io/pointe/issues/new?template=working-group.yml); the issue is public,
so write nothing there you would not publish.

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).
