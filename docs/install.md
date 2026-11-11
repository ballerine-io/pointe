# Install Pointe

**One command** in Terminal (or, in the Claude desktop app's Code tab, type the two `/plugin` commands below):

```
claude plugin marketplace add https://github.com/ballerine-io/pointe.git && claude plugin install pointe@pointe
```

Desktop app: `/plugin marketplace add https://github.com/ballerine-io/pointe.git`, then `/plugin install pointe@pointe`.

Then start a new Claude Code session. It says "Pointe is installed. Run /pointe:setup to finish." Run it: Claude checks
your Mac, installs what is missing, helps you choose model vendors (with measured quality and cost), opens a Mac window
for each key so it goes straight to your Keychain, starts your first voice call, and can set up your phone.

If GitHub refuses (the repository is private for now), ask whoever shared Pointe to give your GitHub account access, or
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
- On the first `/pointe:voice`, about 600 MB of Python packages in the plugin's folder.
- Your keys, in the macOS Keychain only (`pointe key <vendor>` opens the window again).

To remove it: `/pointe:stop`, then remove the plugin in Claude Code's plugin settings.
