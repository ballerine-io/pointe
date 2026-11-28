# Install verification

A record of the documented install path, followed word for word in an environment with nothing of Pointe's in it.
Repeat it before a release and add a section on top ([docs/releasing.md](releasing.md)).

No run yet for 0.10.x; the newest is 0.9.0. The runs numbered 1.x below it are pre-release builds, from before the
public 0.8.0; their versions are those builds' own numbers.

## 2026-11-26, version 0.9.0: the standalone install from github.com

**Machine.** Apple-silicon Mac, macOS 27.0. No Claude Code in the run.

**How clean.** As in the run below: one shell with an empty environment (`env -i`), a new empty `HOME`, `PATH` set to
`/usr/bin:/bin:/usr/sbin:/sbin` and a fake `security` that answers "not found", so no Keychain item was read. No uv,
no `~/.pointe`, no `~/.claude-voice`. Nothing was started, so no port was used.

**The repository is public.** `install.sh` (pinned to 0.9.0 and `72d6dbec…c802`, the release's tarball) downloaded the
tarball from `github.com/ballerine-io/pointe/releases/download/v0.9.0/` as a stranger would, while v0.9.0 was a
prerelease.

| # | Step | Result | Time |
|---|---|---|---|
| 1 | `bash install.sh --yes` | the plan printed first; "SHA-256 matches"; uv 0.12.21 installed with both of its checks; `~/.local/bin/pointe` written; "Pointe 0.9.0 is installed in ~/.pointe/0.9.0" | 69 s |
| 2 | `pointe version`, `bin/pointe-installs list` | "Pointe 0.9.0"; one line, `standalone 0.9.0 ~/.pointe/0.9.0` | |
| 3 | `pointe setup` with no terminal | the setups table | |
| 4 | `pointe update --yes` | "Pointe 0.9.0 is up to date: 0.8.7 is not newer." (0.8.7 was still Latest) | |
| 5 | `pointe uninstall --dry-run`, then `--yes` | lists `~/.pointe` (455 MB); removes it and `~/.local/bin/pointe`: "Pointe is removed."; uv kept | |

**Not covered.** `pointe update` between two published versions from github.com, `pointe setup` at a terminal past its
first question, and the first call, as in the run below. Linux: the hub and node installs ran in CI's Ubuntu smoke and
in docs/linux.md's containers, not here.

## 2026-11-23, version 1.23.0: the standalone install

**Machine.** Apple-silicon Mac, macOS 27.0. No Claude Code in the run.

**How clean.** One shell with an empty environment (`env -i`), a new empty `HOME`, `PATH` set to
`/usr/bin:/bin:/usr/sbin:/sbin`: no uv, no uv cache, no Python of uv's, no `~/.pointe`, no `~/.claude-voice`. A fake
`security` that answers "not found" stood in for the Keychain, so no Keychain item was read. Port 7995.

**The repository is still private.** An anonymous download of the release asset answers 404, so `install.sh` was run on
the asset as published (downloaded with `gh release download v1.23.0`) through `--url file://…`; it then read the
release's own `pointe-1.23.0.tar.gz.sha256` beside it. The pinned-hash path from github.com, and `pointe update`'s
`/releases/latest` lookup, need the repository public (see "Not covered").

| # | Step | Result | Time |
|---|---|---|---|
| 1 | `install.sh` served by the site preview, compared with the repository's | the same bytes; `content-type: application/x-sh`; it pins 1.23.0 and `3e2b700d…0ff5` | |
| 2 | `bash install.sh --yes --url file://…/pointe-1.23.0.tar.gz` | the plan printed first; "SHA-256 matches"; uv 0.12.21 installed with both of its checks; `~/.local/bin/pointe` written; Python 3.12 and the packages downloaded; "Next: ~/.local/bin/pointe setup" | 225 s (uv, Python and the packages over the network) |
| 3 | `pointe version`, `bin/pointe-installs list` | "Pointe 1.23.0"; one line, `standalone 1.23.0 ~/.pointe/1.23.0` | |
| 4 | `pointe setup` with no terminal | the setups table, as before | |
| 5 | `pointe update --yes` | "could not reach github.com to find the newest release" (the 404 above); nothing changed | |
| 6 | `pointe uninstall --dry-run`, then `--yes` | lists `~/.local/bin/pointe` and `~/.pointe` (453 MB); removes both: "Pointe is removed."; uv kept | |

**Not covered.** The download from github.com by a stranger, and `pointe update` against it, until the repository is
public. `pointe setup` at a terminal past its first question, its key window and the first call (they reach the
Keychain and open Chrome, which this run kept out). The `codex` alias and `/voice` in a real Codex and OpenCode. The
tampered-tarball refusal, the update between two versions, and the plugin beside the standalone install ran in
`tests/test_install.py` against test releases, not here.

## 2026-11-23, version 1.20.0

**Machine.** Apple-silicon Mac, macOS 27.0, Claude Code 2.1.330, Chrome installed.

**How clean.** As in the run below: one shell with an empty environment (`env -i`), a new empty `HOME`, `PATH` set to
`$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin`, and only a link to the Claude Code binary in that `HOME`. No uv, no
`~/.claude`, no `~/.claude-voice`, no Keychain. Pointe ran on ports 7993 and 7994, so a running Pointe on this Mac was
not reached.

**The repository is still not public.** The install command was run as written; git in that one shell read its GitHub
address from a local copy of the version commit (`url.<copy>.insteadOf`), as in the run below. Fetching from GitHub as
a stranger is still to be done (see "Not covered").

### Steps and timings

| # | Step | Result | Time |
|---|---|---|---|
| 1 | `claude plugin marketplace add https://github.com/ballerine-io/pointe.git && claude plugin install pointe@pointe` | "Successfully installed plugin: pointe@pointe (scope: user)"; `claude plugin list` shows 1.20.0, enabled | 2.2 s (local copy) |
| 2 | The SessionStart hook (`bin/voice-first-run`) | "Pointe is installed. Run /pointe:setup to finish: about 5 minutes, free with one Google key." `voice-first-run --needed`, which `/pointe:voice` runs first, says `needed` | 0.3 s |
| 3 | Setup step 1: `sw_vers`, Chrome, then `bin/install-uv` | macOS 27.0, Chrome found; uv 0.12.21 installed with both SHA-256 checks, and "pointe is a command now: ~/.local/bin/pointe runs Pointe"; `command -v pointe` finds it and `pointe help` lists the commands | 3.3 s |
| 4 | Setup step 2: `bin/voice-doctor`, the first run | Python 3.12.14 and the packages downloaded; first line "Pointe is not ready: it needs a Gemini key.", then the fix, then the details; exit 1 | 21.6 s |
| 5 | `pointe setup free` | "Setup: Free start. Pointe now uses Gemini, and no other vendor." and the one command for its key | 0.6 s |
| 6 | The daemon as `/pointe:voice` starts it (`bin/voice-daemon ensure`), no key | Refused in words: "It needs a Gemini key", and "Fix it: pointe key gemini (opens the key page and a Mac window, and checks the key)"; nothing left running | 1.6 s |
| 7 | The same with a made-up Gemini key | The key is checked with one tiny call before the daemon starts: "The gemini key was refused…", "Fix it: pointe key gemini…"; exit 1, so no tab would open; nothing left running | 2.9 s |
| 8 | The same key with the check skipped (`CLAUDE_VOICE_SKIP_KEY_CHECK=1`) | Healthy on its port; the page without its key is refused (403); `/voice/status` says version 1.20.0 and `first_call: true` | 1.9 s to healthy |
| 9 | `bin/voice-daemon stop`, then `claude-voice-attach heard 2` with no call | "stopped"; "No first words heard yet. Is the page open? …" | 2.6 s |
| 10 | `pointe uninstall --dry-run`, then `pointe uninstall --yes` | The list: Pointe's command, `~/.claude-voice`, the plugin with its hooks, the marketplace; uv kept. Then each "done", "Pointe is removed."; `claude plugin list` empty | 1.6 s |

From the install command to a daemon that answers: about 31 s of machine time on this link, plus the time to get a key.

### Stumbles, and what was changed

| Stumble | Fix |
|---|---|
| `pointe uninstall` failed at once with "unsupported operand type(s) for \|: 'type' and 'NoneType'": `bin/pointe` runs it with the `python3` on the PATH, which on a new Mac is Apple's 3.9. The tests had run it on 3.12. | `pointe/uninstall.py` reads its annotations lazily; `tests/test_uninstall.py` runs it on `/usr/bin/python3`. |
| With no key, the start still said "Save it: …" and "Check it: …", two commands, while `pointe key` now checks the key itself. | One line: "Fix it: pointe key gemini (opens the key page and a Mac window, and checks the key)". |

### Not covered

- **The fetch from GitHub as a stranger**: run step 1 again, logged out, once the repository is public. Open.
- **`/pointe:setup` driven by Claude**, the key window, the vendor's key page opening, the Keychain prompt, and a real
  key: the clean `HOME` has no Claude sign-in and no Keychain, and no real key was used.
- **A call**: Chrome's microphone prompt, Connect, the first hello and its answer, Cannot hear you on a refused key. They
  are covered by the offline tests only (`tests/test_first_hello.py`).
- **The phone, the apps, the local modes, a new macOS user account, an Intel Mac**, as in the run below.

## 2026-11-19, version 1.14.3

**Machine.** Apple M5 Pro, 64 GB, macOS 27.0 (26A428), Claude Code 2.1.329, Chrome installed. Download speed about
21 MB/s, measured on uv's own binary.

**How clean.** Not a new Mac and not a new macOS user. One shell with an empty environment (`env -i`), a new empty
`HOME`, and `PATH` set to `$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin`. The only thing put in that `HOME` was a
link to the Claude Code binary, where its own installer puts it. So there was no uv, no Python but Apple's, no Node,
no Homebrew, no git configuration, no uv cache, no `~/.claude`, no `~/.claude-voice`, and no key: with a new `HOME`
the `security` tool finds no Keychain ("A default keychain could not be found"). Apple's `git` (2.54.0, from the
command line developer tools) was already installed.

**The repository was not public yet.** The install command was run as written, with its GitHub address. To make that
address answer without a sign-in, git in that one shell was told to read it from a local copy of the same commit
(`url.<copy>.insteadOf`). Fetching from GitHub itself is therefore not part of the timing below; a plain `git clone`
of the repository from GitHub took 2.1 s on this link (13 MB).

### Steps and timings

Every command is the one in [docs/install.md](install.md) or in `/pointe:setup` (`plugin/commands/setup.md`), run by
hand in the order setup runs them.

| # | Step | Result | Time |
|---|---|---|---|
| 1 | `claude plugin marketplace add https://github.com/ballerine-io/pointe.git && claude plugin install pointe@pointe` | "Successfully added marketplace: pointe", "Successfully installed plugin: pointe@pointe (scope: user)"; `claude plugin list` shows 1.14.3, enabled | 1.7 s (local copy) |
| 2 | What a new session is told: `bin/voice-first-run`, the plugin's SessionStart hook | "Pointe is installed. Run /pointe:setup to finish: keys, your first voice call, and your phone." | under 0.1 s |
| 3 | Setup step 1: `sw_vers`, and the check for Chrome in `/Applications` | macOS 27.0; Google Chrome.app found | under 0.1 s |
| 4 | Setup step 2: `command -v uv \|\| ls ~/.local/bin/uv`, then `bin/install-uv` | uv missing; "uv 0.12.21 installed in ~/.local/bin (the installer and the binary were both checked against pinned SHA-256s)" | 1.5 s |
| 5 | Setup step 3: `bin/voice-doctor`, the first run | Python 3.12.14 downloaded (23.9 MiB), 85 packages installed; every key "missing"; the text that says how to add one; port free | 10.3 s |
| 6 | The daemon, started as `/pointe:voice` starts it (`bin/voice-daemon ensure`), with no key | Refused in words: "No model key yet. One key is enough to start…", exit 1, nothing left running | 0.9 s |
| 7 | The same with one made-up Gemini key in the environment, on another port | The daemon answered `/voice/health` with 200, refused the page without its secret (403), and reported version 1.14.3; the doctor named the setup: "28 of 35 audio checks passed… Cost: about $0.70 to $0.95 an hour" | 2.8 s to healthy |
| 8 | `bin/voice-daemon stop` | "stopped"; nothing listening on the port | under 1 s |
| 9 | Removal as documented: `claude plugin uninstall pointe@pointe && claude plugin marketplace remove pointe` | Both succeeded; `claude plugin list` empty; `~/.claude-voice`, `~/.local/share/uv` and `~/.cache/uv` stay, as the removal section says | 1.1 s |

From the install command to a daemon that answers: about 17 s of machine time on this link, plus the time to get a key.

**Disk, measured after step 5:** the plugin's `.venv` 464 MB, `~/.local/share/uv` (the private Python) 70 MB,
`~/.cache/uv` 460 MB. On APFS the `.venv` and the cache share their blocks, so about 530 MB is used, as
[install.md](install.md#what-it-installs) says. The download: 144 MB of wheels by the sizes in `uv.lock`, plus Python
(25 MB) and uv, about 190 MB against the documented "about 180 MB".

### Stumbles, and what was changed

| Stumble | Fix |
|---|---|
| With no GitHub sign-in the install command failed: "HTTPS authentication failed… fatal: unable to get password from user". True only while the repository is private; the docs explained it with "private for now" and a `gh auth` detour. | `docs/install.md` no longer mentions a private repository. The fallback for any failed fetch is the zip from the repository page. This step must be run again against GitHub once the repository is public. |
| The doctor priced a one-key setup without its ears: "about $0.40 an hour plus Gemini ears, not priced here". A new user choosing by cost saw a number that was too low. `/pointe:setup` and the README had the same. | The ears are priced from the vendors' pages: about $0.70 to $0.95 for Gemini only, about $0.95 for OpenAI only (`pointe/doctor.py`, `plugin/commands/setup.md`, README, [benchmarks.md](benchmarks.md#cost-arithmetic)). Version 1.14.3. |
| The doctor and setup say "free tier available" for Gemini and nothing more, while the repository's own test run exhausted a free-tier key. | Setup now says what a free-tier key means before the user chooses it; [install.md](install.md#try-it-for-free-or-cheap) has the path, the limits and the terms. |
| uv's download cache (`~/.cache/uv`, 460 MB) was not in "What it installs", and the removal steps freed it only for a user whose uv setup had installed. | Both are in `docs/install.md` now. |

Nothing else stumbled: no step needed a tool that a Mac with Claude Code and the command line developer tools lacks.

### Not covered

- **A real new Mac or macOS user account**, and a Mac without the command line developer tools (macOS then offers to
  install them; `docs/install.md` says to press Install and run the command again).
- **The fetch from GitHub as a stranger.** See above: run step 1 again, logged out, after the repository is public.
- **Claude Code's own sign-in, and `/pointe:setup` driven by Claude.** The clean `HOME` has no Claude sign-in, so no
  session was started there. The commands setup runs were run by hand, in its order; what Claude says between them, and
  whether Claude Code asks permission for each, was not seen.
- **The key window and the Keychain.** `pointe key <vendor>` opens a macOS dialog and writes to the login Keychain,
  which may ask "Always Allow" the first time the daemon reads it. No Keychain exists in the clean `HOME`, and no real
  key was used.
- **A call.** Chrome's microphone prompt, Connect, a spoken reply, and anything a vendor answers. The key in step 7
  was made up, so no vendor was contacted.
- **The other install paths:** the Claude desktop app's `/plugin` commands, the paste-in prompt, and a zip.
- **The local modes** (`pointe local`, `pointe local voice`): downloads of 2 GB and 17.7 GB, timed in
  [features/local.md](features/local.md#measured) and [features/voice-stays-local.md](features/voice-stays-local.md#measured).
- **The phone**, a slow connection, an Intel Mac, and a macOS version other than 27.0.
