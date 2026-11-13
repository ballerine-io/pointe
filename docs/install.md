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

If GitHub refuses (the repository is private for now; git says "unable to get password from user"), ask whoever shared Pointe to give your GitHub account access, or
for a zip, and use the prompt below.

## Or let Claude do the install too

Open Claude Code (the desktop app's Code tab, or the terminal) in any folder, paste the block below, and send it.
Claude Code does the rest and asks before each step. You need a Mac, Chrome, and headphones.

```
Install Pointe, Ballerine's voice command center for Claude Code, on this Mac. I am not a developer: explain each step in
one plain sentence, do the work yourself, and never ask me to paste a key into this chat.

1. Check that this is macOS and that Google Chrome is installed. If Chrome is missing, tell me to install it and stop.
2. Get Pointe. If I received it as a zip file, unzip it to ~/Pointe and use that folder as the marketplace. Otherwise use
   GitHub, https://github.com/ballerine-io/pointe (private for now): if git cannot read it, install the GitHub CLI if
   needed, run `gh auth login --web` so I sign in in my browser, then `gh auth setup-git`, and try again. If GitHub still
   refuses, tell me to ask the person who shared Pointe to give my GitHub account access, and stop.
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

## What it installs

- The Pointe plugin, into Claude Code's own plugin folder.
- [uv](https://docs.astral.sh/uv/), which runs Pointe's Python, into `~/.local/bin`, if it is missing.
- The first time setup checks your Mac, about 180 MB of Python packages and a private copy of Python (about 530 MB on
  disk), in the plugin's folder and `~/.local/share/uv`. On a fast connection this takes under a minute.
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
