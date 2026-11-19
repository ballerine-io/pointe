# Install verification

A record of the documented install path, followed word for word in an environment with nothing of Pointe's in it.
Repeat it before a release and add a section on top ([RELEASING.md](../RELEASING.md)).

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
| The doctor priced a one-key setup without its ears: "about $0.40 an hour plus Gemini ears, not priced here". A new user choosing by cost saw a number that was too low. `/pointe:setup` and the README had the same. | The ears are priced from the vendors' pages: about $0.70 to $0.95 for Gemini only, about $0.95 for OpenAI only (`doctor.py`, `plugin/commands/setup.md`, README, [benchmarks.md](benchmarks.md#cost-arithmetic)). Version 1.14.3. |
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
