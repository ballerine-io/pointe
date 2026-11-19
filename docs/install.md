# Install Pointe

**One command** in Terminal (or, in the Claude desktop app's Code tab, type the two `/plugin` commands below):

```
claude plugin marketplace add https://github.com/ballerine-io/pointe.git && claude plugin install pointe@pointe
```

Desktop app: `/plugin marketplace add https://github.com/ballerine-io/pointe.git`, then `/plugin install pointe@pointe`.

Then start a new Claude Code session. It says "Pointe is installed. Run /pointe:setup to finish." Run it: Claude checks
your Mac, installs what is missing, helps you choose model vendors (with measured quality and cost), opens a Mac window
for each key so it goes straight to your Keychain, starts your first voice call, and can set up your phone.

If macOS asks to install the command line developer tools, press Install, wait for it to finish, and run the command
again: Claude Code needs `git` to fetch the plugin.

If git cannot fetch the repository (a proxy or a firewall in the way), download it as a zip from
[its GitHub page](https://github.com/ballerine-io/pointe) (Code, then Download ZIP) and use the prompt below, which
also installs from a folder.

## Or let Claude do the install too

Open Claude Code (the desktop app's Code tab, or the terminal) in any folder, paste the block below, and send it.
Claude Code does the rest and asks before each step. You need a Mac, Chrome, and headphones.

```
Install Pointe, Ballerine's voice command center for Claude Code, on this Mac. I am not a developer: explain each step in
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

After setup: run `/pointe:voice` in any session you want to talk to, allow the microphone in the tab that opens, and
press Connect.

## Try it for free or cheap

Prices and free allowances here were read on each vendor's own page on 2026-11-19. They change: check the page. A "busy
hour" is 60 spoken replies, 10 session reports and the call open for the whole hour; it is arithmetic from the
benchmarks and list prices, not a metered bill ([how it is counted](benchmarks.md#cost-arithmetic)).

| Start | You need | A busy hour | Measured |
|---|---|---|---|
| Free | one Google AI Studio key, no card | $0 until the free quota ends | 28 of 35 audio checks on a paid key; a free key ran out during one test run |
| One paid key | the same key with billing on (Google asks for a prepayment of $5 or more) | about $0.70 to $0.95 | 28 of 35; replies take about 4 s; headphones |
| Voice stays on your Mac | an Apple-silicon Mac, 2 GB of disk, one text key (Gemini or Anthropic) | about $0.30 with a Gemini key, about $0.40 with Anthropic and Gemini | 30 of 35 with Anthropic and Gemini; not run with a Gemini key alone |
| Fully local | an Apple-silicon Mac with 32 GB of memory, 19 GB of disk | $0 | 10 of 19 one-session checks; replies take 6 to 12 s |

**The free path.** Make a key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey), then choose "Easiest
start" in `/pointe:setup`. One Gemini key runs every role, and [Google's pricing page](https://aistudio.google.com/docs/pricing)
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
- **It is the weakest keyed setup measured**: replies take about 4 s and there is no echo guard, so use headphones.

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

- The Pointe plugin, into Claude Code's own plugin folder.
- [uv](https://docs.astral.sh/uv/), which runs Pointe's Python, into `~/.local/bin`, if it is missing: one pinned
  version, whose installer is checked against a SHA-256 before it runs (`bin/install-uv`).
- The first time setup checks your Mac, about 180 MB of Python packages and a private copy of Python (about 530 MB on
  disk), in the plugin's folder and `~/.local/share/uv`, with uv's download cache in `~/.cache/uv`. On a fast
  connection this takes under a minute.
- Your keys, in the macOS Keychain only (`pointe key <vendor>` opens the window again).
- Only if you choose a local setup: local libraries (about 290 MB to download, 1.1 GB on disk) in the plugin's folder,
  and models in `~/.cache/huggingface`. "Voice stays on your Mac" adds 2 GB of models. "Fully local" adds 17.7 GB, and
  a 0.4 GB text-model server in `~/.claude-voice/local`.

To remove it: `/pointe:stop`, then remove the plugin in Claude Code's plugin settings (or
`claude plugin uninstall pointe@pointe && claude plugin marketplace remove pointe`). Nothing keeps running. Claude Code
deletes the plugin's folder, with its Python packages, by itself some days later. These stay until you remove them:

- `~/.claude-voice`: Pointe's settings and logs, which hold what was said on calls, and the local text-model server.
  Delete the folder.
- Local models, if you chose a local setup: in `~/.cache/huggingface/hub`, the folders whose names start with
  `models--mlx-community--whisper-large-v3-turbo`, `models--mlx-community--Kokoro-82M` and
  `models--mlx-community--gemma-4`, and `~/.cache/pipecat/kokoro-onnx`. Other apps may share `~/.cache/huggingface`:
  delete only these.
- Your keys: open Keychain Access and delete the items named `gemini-api-key`, `anthropic-api-key`, `soniox-api-key`,
  `elevenlabs-api-key` and `openai-api-key`.
- uv, if setup installed it: `uv cache clean`, then delete `~/.local/bin/uv`, `~/.local/bin/uvx` and `~/.local/share/uv`.
  If uv was yours already, `uv cache clean` alone frees what Pointe's packages took in `~/.cache/uv`.
