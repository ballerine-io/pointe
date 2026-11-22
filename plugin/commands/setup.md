---
description: Set Pointe up on this Mac, start to finish, for someone who does not use a terminal
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/pointe:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/voice-doctor:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/claude-voice-attach:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/voice-daemon:*), Bash(command -v:*), Bash(ls:*), Bash(sw_vers:*), Bash(open:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/install-uv:*), Bash(echo:*), Bash(mkdir -p ~/.claude-voice:*), Bash(touch ~/.claude-voice/setup-done:*)
---

Set Pointe up for the user, start to finish. They may not be a developer. Do the work yourself; explain each step in one
plain sentence before you do it; keep each reply short. Two rules without exception: never ask them to type in a
terminal, and never ask them to paste a key into this chat (a key typed here ends up in the transcript). Keys go only
through the Mac window that `pointe key` opens.

Go in this order and say which step you are on ("Step 2 of 7").

**1. This Mac.** `sw_vers` (macOS needed). Check Chrome: `ls /Applications ~/Applications 2>/dev/null | grep -i "google chrome"`. If Chrome is
missing, ask them to install it from google.com/chrome and come back.

**2. uv**, which runs Pointe's Python: `command -v uv || ls ~/.local/bin/uv`. If missing, say you will install one
pinned version of it with Astral's installer, checked against a known checksum first, then run
`${CLAUDE_PLUGIN_ROOT}/bin/install-uv`.

**3. Choose a setup, then its keys.** Pointe uses AI models from vendors you choose, with your own keys; you pay them
directly. Say these two blocks word for word, once: "Why its own keys? Pointe runs its own models next to Claude Code:
the brain, the reader and the checker, the ears and the voice. Your Claude subscription (Pro or Max) runs Claude Code,
but has no interface other apps can use, so Pointe's voice needs its own API key from console.anthropic.com, or one
Gemini key. An API key is billed per use: about $1 for a busy hour of talk." and "**What do I need?** Any one of these
is enough to start: (a) one Gemini key (free tier; about $0.70 to $0.95 a busy hour with billing on), (b) one OpenAI
key (about $0.95 a busy hour), (c) Soniox + Anthropic API keys (about $1.20). Fastest and most accurate voice:
Anthropic + Soniox + ElevenLabs (+ Gemini for the checker), about $1 a busy hour." If they ask about their Claude Pro or
Max plan, repeat the first block: Pointe cannot use the subscription, and adding it is not on offer.

Run `${CLAUDE_PLUGIN_ROOT}/bin/voice-doctor` with a 10-minute timeout to see which keys exist. The first run downloads
Pointe's Python packages, about 180 MB: say so first ("this downloads what Pointe needs, usually under a minute"). Then
show this table. Never call one setup "the best": say what each one is for, with its numbers.

<!-- setups: written by tools/setups.py from setups.py -->
| Setup (`pointe setup <id>`) | Keys | Measured | A busy hour | Pick it for |
|---|---|---|---|---|
| Free start (`free`) | Gemini | 28 of 35 audio checks on a paid key; a free-tier key ran out of quota in the run (3 of 19); replies took 4.0 to 4.5 s | $0 until the free quota ends; about $0.70 to $0.95 with billing on | just trying it; no budget |
| One OpenAI key (`openai`) | OpenAI | 24 of 35 audio checks; whole replies not measured; the brain answers in 2.4 s at the median | about $0.95 | you already pay for OpenAI |
| Two keys (`two`) | Soniox + Anthropic | 30 of 35 audio checks (31 on a rerun); echo guard 3 of 4, so speakers work; whole replies not measured; the brain answers in 1.8 s at the median, the voice starts in 301 ms | about $1.20 | the best ears with two accounts; laptop speakers |
| Fastest and most accurate voice (`full`) | Anthropic + Soniox + ElevenLabs + Gemini | 34 of 35 audio checks, echo guard 4 of 4: the highest whole-setup result; replies in 2.4 s at the median (2.0 to 2.6), the fastest measured | about $1 | daily use |
| Voice stays on your Mac (`voice-local`) | Anthropic (Gemini optional) | 30 of 35 audio checks, with Anthropic and Gemini keys; replies in 4.1 s at the median | about $0.40 (Anthropic and Gemini) | confidential work where text may leave the Mac but your voice may not |
| Fully local (`local`) | none | 10 of 19 one-session audio checks, every approval check among them; replies took 5.8 to 11.6 s | $0 | nothing may leave the Mac; no budget with a 32 GB Mac |

Sources, speed and where your words go: [docs/setups.md](../../docs/setups.md).
<!-- end setups -->

Ask one question: "Which setup?", with these options, in this order: Free start (recommended if they have no
preference: one key, working in two minutes), Fastest and most accurate voice (for daily use), Two keys, Voice stays on
your Mac (confidential work), Fully local (nothing may leave the Mac). Offer One OpenAI key only if they say they have
one. If a key the doctor already found fills a setup, say so: that setup needs nothing more.

Then run `${CLAUDE_PLUGIN_ROOT}/bin/pointe setup <id>` with a 10-minute timeout. It saves the choice, so Pointe uses
exactly that setup's vendors from now on and ignores other keys; `pointe setup` again switches later. For
`voice-local` it downloads the local libraries and two models (about 2.3 GB, once; about a minute and a half on a fast
link); for `local` everything the fully local mode needs (about 8 minutes on a fast link) and it starts the local
model: run that one in the background, as it outlasts a normal command, and tell them briefly what it prints. If it says
the Mac is not supported, offer Free start instead.

Then ask only for the keys that setup needs and the doctor did not find, one at a time. For each: tell them first "A
small Mac window will open. Paste the key there and press Save. It goes straight into your Mac's Keychain, the same safe
place that holds your passwords; it is never written in a file or shown here." Run
`${CLAUDE_PLUGIN_ROOT}/bin/pointe key <vendor>`, then `${CLAUDE_PLUGIN_ROOT}/bin/pointe key check <vendor>`, which makes
one tiny live call and prints only whether the key works. If it was refused, say so and run `pointe key <vendor>` again.
Where to get each key: console.anthropic.com/settings/keys, console.soniox.com, elevenlabs.io/app/settings/api-keys,
aistudio.google.com/apikey, platform.openai.com/api-keys. If the Mac asks to allow access to the Keychain, tell them to
press Always Allow. When every key works, run the doctor again and confirm in one line. It marks the keys the setup does
not use as "optional": say those are not needed, never that they are missing.

A Gemini key without billing is on Google's free tier. If they choose Free start with one, say two things in plain
words: on that tier Google may use and review what is sent, so it is for trying Pointe on work that is not confidential;
and the free quota is small, so when replies start to fail they turn billing on for the same key and nothing else changes.

Voice stays on your Mac hears and speaks on the Mac, so no recording of their voice goes to any vendor; the brain is
still Anthropic's Claude and gets text only. It cannot speak Hebrew, and on laptop speakers interrupting it by voice takes
3 to 4 seconds, so recommend headphones. Fully local needs an Apple-silicon Mac with 32 GB of memory or more, and about
19 GB of disk; it is free and private, and slower and less accurate than the keyed setups, and it cannot speak Hebrew.

What leaves the Mac: the table's last columns say it per setup (docs/setups.md). Say it in one line, and that they should
use vendors their company allows.

**4. First call.** Run `${CLAUDE_PLUGIN_ROOT}/bin/claude-voice-attach`. The first start takes up to a minute, then a
Chrome tab opens. Tell them: put on headphones, allow the microphone, press Connect, and say "what are
you working on?". Explain: every Claude Code session where they run /pointe:voice joins the same voice; say a session's
name to talk to it; "brain dump" (or "just listen") makes it stay quiet while they dump thoughts, then structures them for review; permission prompts are read out and a
plain yes or no answers them, and anything complex waits for a tap on the page.

**5. Phone (optional).** Ask if they want Pointe on their phone. The phone needs a private way to reach this Mac. Offer:
- Tailscale (easiest, free for personal use): install it on the Mac (tailscale.com/download) and the phone, sign in to
  the same account on both, then run `${CLAUDE_PLUGIN_ROOT}/bin/pointe pair tailscale`.
- Their company VPN, such as Twingate, if it routes to this Mac: run `${CLAUDE_PLUGIN_ROOT}/bin/pointe pair host <name>`.
- Same Wi-Fi only: `${CLAUDE_PLUGIN_ROOT}/bin/pointe pair wifi`.
Pairing shows a QR code. If it does not show here, save it: `${CLAUDE_PLUGIN_ROOT}/bin/pointe pair show`, and open what
it prints. The iPhone app is not in the App Store or on TestFlight yet; step 6 builds it. Without it, the same page
works in the phone's browser.

**6. The Mac app and the iPhone app (optional).** Pointe has a Mac app (the call in the menu bar, no browser tab) and an
iPhone app. Neither has a download yet: each is built on this Mac with Xcode, by one command. Ask if they want either;
if not, go to step 7. Check Xcode first: `ls /Applications | grep -i xcode`. If Xcode is missing, say it is a free,
large (about 12 GB) install from the App Store, that it is only for these two apps, and that they can come back to this
later; do not push it on someone who is not a developer. With Xcode there, run
`${CLAUDE_PLUGIN_ROOT}/bin/pointe apps doctor` and read them what it found in plain words. It never prints a Team ID.
- The Mac app needs no Apple Account: run `${CLAUDE_PLUGIN_ROOT}/bin/pointe apps mac --open` with a 15-minute timeout
  (the first build takes a few minutes). It installs to ~/Applications and opens; its mark appears in the menu bar.
- The iPhone app needs an Apple Account signed in to Xcode (a free one is enough) and the iPhone connected. When the
  doctor says something is missing, walk them through its fix one step at a time; the steps are in Xcode's Settings and
  on the iPhone, never in a terminal. Then run `${CLAUDE_PLUGIN_ROOT}/bin/pointe apps ios` with a 15-minute timeout.
  Tell them: with a free account the app opens for 7 days, and the same command renews it. When the fix is a `sudo`
  command (the Xcode license, `xcode-select`), do not ask them to type it: opening Xcode once accepts the license in a
  window, and Xcode's Settings, Locations, Command Line Tools selects Xcode.
- No iPhone or no Apple Account: `${CLAUDE_PLUGIN_ROOT}/bin/pointe apps ios --sim` shows the app in the Simulator.
If a build fails, read them the cause and the fix the command printed; the same table is in docs/phone.md, "Getting the
app". After the iPhone app is installed, pair it as in step 5.

**7. Done.** Run `mkdir -p ~/.claude-voice && touch ~/.claude-voice/setup-done` so new sessions stop suggesting setup. Summarize in three lines: what setup they have, how to start (/pointe:voice), how to stop (/pointe:stop),
and that /pointe:doctor shows what runs and what to improve. Ask them to report anything confusing as an issue at github.com/ballerine-io/pointe.
