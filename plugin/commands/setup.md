---
description: Set Pointe up on this Mac, start to finish, for someone who does not use a terminal
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/pointe:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/voice-doctor:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/claude-voice-attach:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/voice-daemon:*), Bash(command -v:*), Bash(ls:*), Bash(sw_vers:*), Bash(open:*), Bash(curl -LsSf https\://astral.sh/uv/install.sh:*), Bash(sh:*), Bash(echo:*), Bash(mkdir -p ~/.claude-voice:*), Bash(touch ~/.claude-voice/setup-done:*)
---

Set Pointe up for the user, start to finish. They may not be a developer. Do the work yourself; explain each step in one
plain sentence before you do it; keep each reply short. Two rules without exception: never ask them to type in a
terminal, and never ask them to paste a key into this chat (a key typed here ends up in the transcript). Keys go only
through the Mac window that `pointe key` opens.

Go in this order and say which step you are on ("Step 2 of 6").

**1. This Mac.** `sw_vers` (macOS needed). Check Chrome: `ls /Applications ~/Applications 2>/dev/null | grep -i "google chrome"`. If Chrome is
missing, ask them to install it from google.com/chrome and come back.

**2. uv**, which runs Pointe's Python: `command -v uv || ls ~/.local/bin/uv`. If missing, say you will install it with
Astral's official installer, then run `curl -LsSf https://astral.sh/uv/install.sh | sh`.

**3. Keys.** Pointe uses AI models from vendors you choose, with your own keys; you pay them directly. Run
`${CLAUDE_PLUGIN_ROOT}/bin/voice-doctor` with a 10-minute timeout to see which keys exist. The first run downloads Pointe's
Python packages, about 180 MB: say so first ("this downloads what Pointe needs, usually under a minute"). Then show this table, and say what each key does:

| Setup | Keys | Measured quality (35 real-call checks) | A busy hour |
|---|---|---|---|
| Best | Anthropic, Soniox, ElevenLabs, Gemini | 33 of 35, works on laptop speakers | about $1 |
| Two keys | Anthropic, Soniox | 30 of 35 | about $1.20 |
| Easiest start | Gemini only (free tier available) | 27 of 35, needs headphones, replies take ~4 s | about $0.40 |
| One key, OpenAI | OpenAI only | 29 of 35, needs headphones, weak on Hebrew | about $0.60 |

What each one does: Soniox hears you (the best speech recognition we measured, Hebrew and English), Anthropic's Claude
decides what to say and reads your sessions, ElevenLabs is the voice, Gemini checks each request before it is sent.
Where to get them: console.anthropic.com/settings/keys, console.soniox.com, elevenlabs.io/app/settings/api-keys,
aistudio.google.com/apikey, platform.openai.com/api-keys.

Recommend: "Easiest start" if they want to try it in two minutes; "Best" if they will use it daily. Ask which, then for
each key, one at a time, run `${CLAUDE_PLUGIN_ROOT}/bin/pointe key <vendor>` (gemini, anthropic, soniox, elevenlabs,
openai). Tell them first: "A small Mac window will open. Paste the key there and press Save. It goes straight into your
Mac's Keychain, the same safe place that holds your passwords; it is never written in a file or shown here." After each
one, run the doctor again and confirm in one line. If the Mac asks to allow access to the Keychain, tell them to press
Always Allow.

What leaves the Mac: their speech goes to the ears vendor, and their sessions' content to the others. Say so in one line,
and that they should use vendors their company allows.

**4. First call.** Run `${CLAUDE_PLUGIN_ROOT}/bin/claude-voice-attach`. The first start takes up to a minute, then a
Chrome tab opens. Tell them: put on headphones, allow the microphone, press Connect, and say "what are
you working on?". Explain: every Claude Code session where they run /pointe:voice joins the same voice; say a session's
name to talk to it; "just listen" makes it stay quiet while they think out loud; permission prompts are read out and a
plain yes or no answers them, and anything complex waits for a tap on the page.

**5. Phone (optional).** Ask if they want Pointe on their phone. The phone needs a private way to reach this Mac. Offer:
- Tailscale (easiest, free for personal use): install it on the Mac (tailscale.com/download) and the phone, sign in to
  the same account on both, then run `${CLAUDE_PLUGIN_ROOT}/bin/pointe pair tailscale`.
- Their company VPN, such as Twingate, if it routes to this Mac: run `${CLAUDE_PLUGIN_ROOT}/bin/pointe pair host <name>`.
- Same Wi-Fi only: `${CLAUDE_PLUGIN_ROOT}/bin/pointe pair wifi`.
Pairing shows a QR code. If it does not show here, save it: `${CLAUDE_PLUGIN_ROOT}/bin/pointe pair show`, and open what
it prints. The iPhone app is not in the App Store yet; whoever shared Pointe can install it for them. Until then, the
same page works in the phone's browser.

**6. Done.** Run `mkdir -p ~/.claude-voice && touch ~/.claude-voice/setup-done` so new sessions stop suggesting setup. Summarize in three lines: what setup they have, how to start (/pointe:voice), how to stop (/pointe:stop),
and that /pointe:doctor shows what runs and what to improve. Ask them to tell whoever shared Pointe what was confusing.
