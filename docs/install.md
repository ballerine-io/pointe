# Install Pointe

Pointe is a voice layer for your coding agents. On a Mac, install it the way any Mac app installs: download
`Pointe.dmg`, drag Pointe to Applications, open it. The other ways in, for a person who works in Claude Code, Codex or
OpenCode, follow under [Other ways](#other-ways). To work on Pointe itself, see [CONTRIBUTING.md](../CONTRIBUTING.md).

## Mac: download Pointe.dmg, drag to Applications, open

1. Download `Pointe-<version>.dmg` from the [newest release](https://github.com/ballerine-io/pointe/releases/latest).
2. Open it and drag Pointe to Applications.
3. Open Pointe from Applications.

The app sets up the rest, in one window with a progress bar, in about five minutes:

1. **Pointe.** Press Install Pointe. The app runs the same installer as the terminal way, `install.sh`, from a copy
   inside the app that it checks against a SHA-256 built into it. That installer downloads the release of the app's own
   version, checks it against the SHA-256 pinned in it, installs uv the checked way and Pointe's Python (about 180 MB),
   and makes `pointe` a command. No Terminal and no password. It installs nothing when Pointe is here already: an
   existing plugin or standalone install is found and used, and the newer of the two runs, as below.
2. **Your setup.** One question: Start with Free start, or choose another setup from the menu.
3. **Your key.** Add… opens the vendor's key page in your browser and a small Mac window for the key, which goes
   straight to your Keychain; Pointe tries it with one tiny call.
4. **Your first call.** Start Pointe, put on headphones, press Connect (macOS asks for the microphone the first time),
   and say hello: Pointe answers that it hears you.

The disk image and the app are signed by Ballerine with Developer ID and notarized by Apple: macOS opens them without
a warning.
`Pointe.dmg` has its SHA-256 beside it on the release page.

**Updates.** When Pointe in your home folder is older than the app, the app shows Update Pointe to <version> at the top
of its window: it installs the app's version beside the old one, checked, restarts Pointe on it (a call in progress
ends), and removes the old one. `pointe update` in a terminal does the same. A Claude Code plugin install updates
through Claude Code, as below: the app never installs a second copy beside it. The app itself: download the new
`Pointe.dmg` and drag it to Applications again.

**Uninstall.** In the app, Pointe → Uninstall Pointe… lists what Pointe added to this Mac, asks once (your keys only if
you tick their box), removes it, the app included, and quits. `pointe uninstall` in a terminal does the same.

Codex and OpenCode sessions join from a terminal, `pointe join codex` or `pointe join opencode` (below); a Claude Code
session joins with `/pointe:voice` once the plugin is installed too.

## Other ways

Install it the way that fits the agent you use: the Claude Code plugin, or the standalone install, which needs no
Claude Code and is the way in for Codex and OpenCode. Both can be on the same Mac: one Pointe runs, the newer one
([The standalone install](#the-standalone-install)).

### Claude Code

**One command** in Terminal (or, in the Claude desktop app's Code tab, type the two `/plugin` commands below):

```
claude plugin marketplace add https://github.com/ballerine-io/pointe.git && claude plugin install pointe@pointe
```

Desktop app: `/plugin marketplace add https://github.com/ballerine-io/pointe.git`, then `/plugin install pointe@pointe`.

Then open a new Claude Code session and run `/pointe:setup`: about 5 minutes, free with one Google key. The session
says "Pointe is installed. Run /pointe:setup to finish." Claude checks your Mac and installs what is missing, asks one
question ("Start with Free start?"; the other setups only if you ask), opens the vendor's key page and a Mac window for
the key so it goes straight to your Keychain, checks the key with one tiny call, and starts your first call. Say
"hello": Pointe answers that it hears you, and setup says "Pointe heard you. You're set up." Your phone, the Mac app and
faster setups come after, as optional extras.

### Codex

```
curl -fsSLO https://eng.ballerine.com/pointe/install.sh
bash install.sh
pointe setup
```

`install.sh` says what it will do and asks first ([The standalone install](#the-standalone-install)). `pointe setup` is
the same one-question flow as `/pointe:setup`, in the terminal: it checks your Mac, asks "Start with Free start?", opens
the key page and the Mac window for the key, and starts your first call; the page opens, and you say hello. Then, if
Codex is on the Mac, it sets Codex up for the voice:

- It starts Codex's shared app-server (`codex app-server daemon start`). Pointe joins a Codex session through it: a
  `codex` started with `--remote unix://` is its client, so Pointe sees and sends to the thread you type in.
- It shows this line and asks before it adds it to `~/.zshrc` (or `~/.bash_profile`), so every `codex` starts the
  app-server if it is not running and connects to it:

  ```
  alias codex='command codex app-server daemon start >/dev/null 2>&1; command codex --remote unix:// -C "$PWD"'
  ```

Then start `codex` in a project folder (in a new terminal, so the line takes effect), and join it to the voice from
that folder, in another terminal:

```
pointe join codex
```

`pointe setup codex` does the Codex part again on its own. [Harnesses](harnesses.md#codex-cli-pointeharnessescodexpy) has how
the join works.

### OpenCode

```
curl -fsSLO https://eng.ballerine.com/pointe/install.sh
bash install.sh
pointe setup
```

The same first setup as for Codex. Then, if OpenCode is on the Mac, it adds a `/voice` command to OpenCode
(`pointe join opencode --install-command`). Restart OpenCode, and type `/voice` in a session to join it. The command has
not yet been run in a real OpenCode; `pointe join opencode`, in the session's folder, joins it the tested way.
`pointe setup opencode` does the OpenCode part again on its own.

### The standalone install

`install.sh` is served at `https://eng.ballerine.com/pointe/install.sh` and is
[`install.sh` in the repository](../install.sh). Download it to a file, read it if you like, and run it with `bash`:
nothing is piped into a shell. It runs as you, with no `sudo`, shows what it will do, and asks before it does it
(`--yes` answers for a script). It:

1. Downloads one release, `pointe-<version>.tar.gz`, from the repository's GitHub Releases, and checks it against the
   SHA-256 written in the installer (or, for another version with `--version`, the SHA-256 published with that release).
   On any difference it stops before anything is unpacked.
2. Unpacks it into `~/.pointe/<version>`.
3. Installs uv into `~/.local/bin` if it is missing, the same checked way the plugin does (`bin/install-uv`).
4. Installs Pointe's Python packages into `~/.pointe/<version>/.venv`, from `uv.lock` (about 180 MB to download).
5. Makes `pointe` a command: `~/.local/bin/pointe`.

**Updates.** `pointe update` finds the newest release, checks it against the SHA-256 published with it, installs it
beside the old one, restarts Pointe on it if Pointe ran from the old one (a call in progress ends), and then removes the
old one. It asks first; `--yes` for a script. The plugin updates through Claude Code: `claude plugin marketplace update
pointe`, then `claude plugin update pointe@pointe`, then `pointe restart`.

**Both on one Mac.** The plugin and the standalone install can both be here. There is still one daemon and one
`~/.local/bin/pointe`: both go to the newer version (the standalone install on a tie), and a start from the other one
hands over to it. `pointe doctor` lists both under "Installed" and says which one runs.

**Not as a Python tool.** `uvx` and `uv tool install` from the git tag do not work cleanly, so they are not offered:
Pointe is not a Python package (it runs from its folder: shell scripts, the page, the hooks), and `uv tool install`
resolves the dependencies again instead of installing the hashes in `uv.lock`.

## Which keys

**What do I need?** Any one of these is enough to start: (a) one Gemini key (free tier; about $0.70 to $0.95 a busy
hour with billing on), (b) one OpenAI key (about $0.95 a busy hour), (c) Soniox + Anthropic API keys (about $1.20).
Fastest and most accurate voice: Anthropic + Soniox + ElevenLabs (+ Gemini for the checker), about $1 a busy hour.

Why its own keys? Pointe runs its own models next to Claude Code: the brain, the reader and the checker, the ears and
the voice. Your Claude subscription (Pro or Max) runs Claude Code, but has no interface other apps can use, so
Pointe's voice needs its own API key from console.anthropic.com, or one Gemini or OpenAI key. An API key is billed
per use: about $1 for a busy hour of talk.

The setups side by side, what each key does in them, what each measured and where your words go:
[setups.md](setups.md). `/pointe:setup` and `pointe setup` start you on Free start unless you ask for another, then ask
only for its keys; [Try it for free or cheap](#try-it-for-free-or-cheap) has the free and cheap ways in.

## What this does to your Mac

- **Installs** the plugin into Claude Code's plugin folder, or, with `install.sh` or the Mac app, a checked release into
  `~/.pointe/<version>`; [uv](https://docs.astral.sh/uv/) into `~/.local/bin` if it
  is missing (one pinned version, its installer checked against a SHA-256 first); about 180 MB of Python packages on
  the first run (about 530 MB on disk); and `~/.local/bin/pointe`, so `pointe` is a command in your terminal.
- **Adds four Claude Code hooks** (the plugin only), active in every session: `PermissionRequest` (while Pointe runs, it holds the
  permission prompts of the sessions you joined so you can answer them by voice; with Pointe stopped it exits at once),
  `PreToolUse` and `PostToolUse` (`voice-stop-hook`: ends a joined session's turn at its next tool step after you say
  "stop") and `SessionStart` (one file check, to suggest `/pointe:setup` until it is done).
- **Runs** one daemon on `127.0.0.1:7860`, started by `/pointe:voice` or `pointe open`, until `/pointe:stop` or a restart of the Mac.
  Nothing starts at login unless you turn that on in the Mac app. During a call from your phone, on mains power, it
  runs `caffeinate -i` so the Mac does not sleep under the call. After you pair a phone it also listens on port 7443.
- **Stores** your keys in the macOS Keychain only, as `pointe.<vendor>-api-key`; settings, logs and a journal of each
  call in `~/.claude-voice` (the journal rotates at 20 MB).
- **Sends** your speech and your sessions' text to the vendors of the setup you choose, with your keys; and sends
  nothing to Ballerine.
- **Removes all of it** with `pointe uninstall`: it lists each item, asks, and deletes Keychain items only on their own
  yes. [What it installs](#what-it-installs) has the sizes and folders.

If macOS asks to install the command line developer tools, press Install, wait for it to finish, and run the command
again: Claude Code needs `git` to fetch the plugin. The standalone install needs no `git`.

If git cannot fetch the repository (a proxy or a firewall in the way), download it as a zip from
[its GitHub page](https://github.com/ballerine-io/pointe) (Code, then Download ZIP) and use the prompt below, which
also installs from a folder.

## Or let Claude do the install too

Open Claude Code (the desktop app's Code tab, or the terminal) in any folder, paste the block below, and send it.
Claude Code does the rest and asks before each step. You need a Mac, Chrome, and headphones.

```
Install Pointe, an open-source voice tool for Claude Code, on this Mac. I am not a developer: explain each step in
one plain sentence, do the work yourself, and never ask me to paste a key into this chat.

1. Check that this is macOS and that Google Chrome is installed. If Chrome is missing, tell me to install it and stop.
2. Get Pointe. If I have it as a zip file, unzip it to ~/Pointe and use that folder as the marketplace. Otherwise use
   GitHub, https://github.com/ballerine-io/pointe. If git cannot fetch it, show me what git said, tell me to download
   the zip from that page (Code, then Download ZIP), and stop.
   Then add the marketplace (the folder, or https://github.com/ballerine-io/pointe.git) and install the plugin
   "pointe@pointe" for my user: with `claude plugin marketplace add <it>` and `claude plugin install pointe@pointe` if the
   `claude` command exists; if not, add the marketplace and enable the plugin in ~/.claude/settings.json
   (extraKnownMarketplaces and enabledPlugins), keeping everything already there.
3. Tell me to start a new Claude Code session so the plugin loads, then to run /pointe:setup there. It checks this Mac,
   helps me choose model vendors (with measured quality and cost), opens a Mac window for each key so the keys go
   straight to my Keychain, starts my first voice call, and can set up my phone.
```

After setup: run `/pointe:voice` in any session you want to talk to, allow the microphone in the tab that opens,
press Connect, and say hello. If setup has not run yet, `/pointe:voice` says to run `/pointe:setup` first.

The last time this path was followed word for word on a clean environment, with timings and what it did not cover:
[install-verification.md](install-verification.md).

## Try it for free or cheap

Prices and free allowances here were read on each vendor's own page on 2026-11-19. They change: check the page. A "busy
hour" is 60 spoken replies, 10 session reports and the call open for the whole hour; it is arithmetic from the
benchmarks and list prices, not a metered bill ([how it is counted](benchmarks.md#cost-arithmetic)).

| Start | You need | A busy hour | Measured |
|---|---|---|---|
| Free | one Google AI Studio key, no card | $0 until the free quota ends | 28 of 35 audio checks on a paid key; a free key ran out during one test run |
| One paid key | the same key with billing on (Google asks for a prepayment of $5 or more) | about $0.70 to $0.95 | 28 of 35; replies take about 4 s; headphones |
| Voice stays on your Mac | an Apple-silicon Mac, about 3 GB of disk, one text key (Gemini or Anthropic) | about $0.30 with a Gemini key, about $0.40 with Anthropic and Gemini | 30 of 35 with Anthropic and Gemini; not run with a Gemini key alone |
| Fully local | an Apple-silicon Mac with 32 GB of memory, 19 GB of disk | $0 | 10 of 19 one-session checks; replies take 6 to 12 s |

**The free path.** Say yes to "Start with Free start?" in `/pointe:setup`: it opens
[aistudio.google.com/apikey](https://aistudio.google.com/apikey) for you to make the key. One Gemini key runs every role, and [Google's pricing page](https://aistudio.google.com/docs/pricing)
lists each model Pointe uses with it (`gemini-3.8-flash`, `gemini-3.5-flash-lite`, `gemini-3.8-flash-lite-tts`,
`gemini-3.5-transcribe-live`) as "Free of charge" on the free tier. Three things to know before you rely on it:

- **The quota is small and Google does not publish it.** The limits show only inside AI Studio. In our audio test a
  free-tier key ran out within one run: 3 of 19 checks passed, the rest failed on HTTP 429
  ([`bench/results/combinations.md`](../bench/results/combinations.md)). That run sends requests faster than a person
  talks; how long a real first call lasts on a free key is not measured. When requests are refused, turn billing on for
  the same key and change nothing else.
- **The free tier is not private.** Google's [terms](https://aistudio.google.com/docs/terms) say that on unpaid
  services it uses what you send "to provide, improve, and develop Google products", that "human reviewers may read,
  annotate, and process your API input and output", and "Do not submit sensitive, confidential, or personal information
  to the Unpaid Services." Pointe sends your speech and your sessions' content to the model. Try the free tier on a
  project you could publish. The same terms allow only paid services "when making API Clients available to users" in
  the European Economic Area, Switzerland or the United Kingdom.
- **Replies take about 4 s** and there is no echo guard, so use headphones.

**A 16 GB Mac.** Fully local mode is not offered below 32 GB: its text model takes 17 GB of memory while it runs. The
one smaller model measured, Qwen3.5-9B (5.3 to 7.6 GB), passed 62.0% of the brain cases against 76.9%, with 35 unwanted
sends of 234 against 16 ([`bench/results/local.md`](../bench/results/local.md)), so it is not a mode.
`pointe local --model <mlx-community model>` runs a smaller model by hand, unmeasured. What does fit is
[Voice stays on your Mac](features/voice-stays-local.md) (`pointe local voice`): Whisper and Kokoro run on the Mac, no
text model does, so no audio leaves it and one text key pays for the brain only. It was measured on one M5 Pro with
64 GB, not on a 16 GB Mac.

**Other free allowances**, for a better voice or ears on top of the one key: ElevenLabs' free plan includes 20,000
characters a month on its Turbo models, about two busy hours of speech, and 2 hours 30 minutes of realtime
transcription ([elevenlabs.io/pricing/api](https://elevenlabs.io/pricing/api)). Anthropic says "New users receive free
credits to test the API" and names no amount ([pricing](https://platform.claude.com/docs/en/about-claude/pricing)).
The pricing pages of [OpenAI](https://developers.openai.com/api/docs/pricing) and [Soniox](https://soniox.com/pricing)
name no free credit.

## What it installs

- The Pointe plugin, into Claude Code's own plugin folder. Or, with `install.sh`, one release in
  `~/.pointe/<version>` (about 7 MB before its Python packages); `pointe update` replaces it with the next.
- [uv](https://docs.astral.sh/uv/), which runs Pointe's Python, into `~/.local/bin`, if it is missing: one pinned
  version, whose installer is checked against a SHA-256 before it runs (`bin/install-uv`).
- The first time setup checks your Mac, about 180 MB of Python packages and a private copy of Python (about 530 MB on
  disk), in the plugin's folder (or `~/.pointe/<version>`) and `~/.local/share/uv`, with uv's download cache in `~/.cache/uv`. On a fast
  connection this takes under a minute.
- Your keys, in the macOS Keychain only, as `pointe.gemini-api-key`, `pointe.anthropic-api-key` and so on
  (`pointe key <vendor>` opens the window again). A key saved by a pre-release build keeps its plain name (`gemini-api-key`)
  and still works.
- `~/.local/bin/pointe`, a three-line script that runs the plugin's `bin/pointe` (or the standalone install's), so
  `pointe` is a command in a new terminal. Each start of Pointe points it at the newest installed version. One you made yourself is never
  replaced.
- Only if you say yes in `pointe setup` or `pointe setup codex`: two lines at the end of `~/.zshrc` (or
  `~/.bash_profile`), the `codex` alias and a comment above it. Only on a yes in `pointe setup`, or with
  `pointe setup opencode`: `/voice` for OpenCode, in
  `~/.config/opencode/plugins/pointe-voice.ts`.
- Only if you choose a local setup: local libraries (about 290 MB to download, 1.1 GB on disk) in the plugin's folder,
  and models in `~/.cache/huggingface`. "Voice stays on your Mac" adds 2 GB of models. "Fully local" adds 17.7 GB, and
  a 0.4 GB text-model server in `~/.claude-voice/local`.

To remove it, run `pointe uninstall` in a terminal (or `~/.local/bin/pointe uninstall`). It lists what is on this Mac
and asks before it removes anything, in three groups, each with its own question:

- Pointe's own: it stops Pointe, then removes `~/.local/bin/pointe`, `~/.claude-voice` (settings, logs that hold what
  was said on calls, phone pairings, the local text-model server), `~/Applications/Pointe.app` (and the disk image's
  `/Applications/Pointe.app`, when it is Pointe's) and its settings
  (`defaults delete io.ballerine.pointe.mac`), `/voice` in OpenCode and the `codex` alias if setup added them,
  `~/.cache/pipecat/kokoro-onnx`, and last the standalone install (`~/.pointe`) and the plugin and its marketplace
  (`claude plugin uninstall pointe@pointe`, `claude plugin marketplace remove pointe`). Each install's folder holds its
  Python packages; the plugin's also holds its hooks.
- Pointe's keys: the Keychain items `pointe.<vendor>-api-key`. Removed only on a yes to this question, or with
  `--delete-keys`.
- What another tool may share: keys under the plain names pre-release builds of Pointe used (`gemini-api-key`,
  `anthropic-api-key`, `soniox-api-key`, `elevenlabs-api-key`, `openai-api-key`), and the local models in
  `~/.cache/huggingface/hub` (`models--mlx-community--whisper-large-v3-turbo`, `models--mlx-community--Kokoro-82M-bf16`,
  `models--mlx-community--gemma-4-26b-a4b-it-4bit`, `models--deepdml--faster-whisper-large-v3-turbo-ct2`). Removed only
  on a yes.

`pointe uninstall --dry-run` only lists them. uv stays, as other tools use it: if setup installed it, `uv cache clean`,
then delete `~/.local/bin/uv`, `~/.local/bin/uvx` and `~/.local/share/uv`.
