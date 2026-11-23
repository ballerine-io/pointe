---
description: Set Pointe up on this Mac, start to finish, for someone who does not use a terminal
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/pointe setup:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/pointe key:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/pointe apps doctor:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/pointe apps mac:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/pointe apps ios:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/voice-doctor:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/claude-voice-attach:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/install-uv:*), Bash(ls /Applications:*), Bash(sw_vers:*), Bash(mkdir -p ~/.claude-voice), Bash(touch ~/.claude-voice/setup-done)
---

Set Pointe up for the user, start to finish: about 5 minutes, free with one Google key. They may not be a developer.
Do the work yourself; say each step in one plain sentence before you do it; keep each reply short. Two rules without
exception: never ask them to type in a terminal, and never ask them to paste a key into this chat (a key typed here ends
up in the transcript). Keys go only through the Mac window that `pointe key` opens.

If the arguments say `apps` or `phone`, go straight to that optional extra at the end. Otherwise there are four steps;
say which one you are on ("Step 2 of 4"). The optional extras come after, and are not steps.

**Step 1 of 4: this Mac.** `sw_vers` (macOS needed). Check Chrome: `ls /Applications ~/Applications 2>/dev/null | grep -i
"google chrome"`. If Chrome is missing, ask them to install it from google.com/chrome and come back. Then uv, which runs
Pointe's Python: run `${CLAUDE_PLUGIN_ROOT}/bin/install-uv`. If uv is missing, say first that it installs one pinned version with Astral's
installer, checked against a known checksum. It also makes `pointe` a command in the terminal (`~/.local/bin/pointe`):
say so in one line.

**Step 2 of 4: your setup.** Run `${CLAUDE_PLUGIN_ROOT}/bin/voice-doctor` with a 10-minute timeout. The first run downloads Pointe's
Python packages, about 180 MB: say so first ("this downloads what Pointe needs, usually under a minute"). Read only its
first line back.

If the doctor found keys that already fill a setup (its "Setup" or "Keys" lines), skip the question below and say so in
one line, for example "Your Anthropic and Soniox keys fill the Two keys setup. Using it.", then run
`${CLAUDE_PLUGIN_ROOT}/bin/pointe setup <id>` and go to step 3.

Otherwise say this, word for word: "Pointe needs its own model key: your Claude subscription cannot be used by other
apps. The quickest start is Free start: one Google key, no card, $0 until the free quota ends. Google may review what
you send on the free tier, so try it on work that is not confidential." Then ask one question, "Start with Free start?",
with these options in this order: "Yes, Free start (recommended)", "Show me the other setups", "I already have keys".

- Yes: run `${CLAUDE_PLUGIN_ROOT}/bin/pointe setup free`.
- Show me the other setups: show the table below, never call one setup "the best", and ask which one; then run
  `${CLAUDE_PLUGIN_ROOT}/bin/pointe setup <id>` with a 10-minute timeout.
- I already have keys: ask which vendors (Gemini, OpenAI, Anthropic, Soniox, ElevenLabs), pick the setup whose keys
  they have from the table, say which in one line, and run `${CLAUDE_PLUGIN_ROOT}/bin/pointe setup <id>`.

<details><summary>The six setups: only when they ask</summary>

<!-- setups: written by tools/setups.py from setups.py -->
| Setup (`pointe setup <id>`) | Keys | Measured | A busy hour | Best for |
|---|---|---|---|---|
| Free start (`free`) | Gemini | 28 of 35 audio checks on a paid key; a free-tier key ran out of quota in the run (3 of 19); replies took 4.0 to 4.5 s | $0 until the free quota ends; about $0.70 to $0.95 with billing on | trying Pointe at no cost |
| One OpenAI key (`openai`) | OpenAI | 24 of 35 audio checks; whole replies not measured; the brain answers in 2.4 s at the median | about $0.95 | people who already pay for OpenAI |
| Two keys (`two`) | Soniox + Anthropic | 30 of 35 audio checks (31 on a rerun); echo guard 3 of 4, so speakers work; whole replies not measured; the brain answers in 1.8 s at the median, the voice starts in 301 ms | about $1.20 | the best ears with two accounts, on laptop speakers |
| Fastest and most accurate voice (`full`) | Anthropic + Soniox + ElevenLabs + Gemini | 34 of 35 audio checks, echo guard 4 of 4: the highest whole-setup result; replies in 2.4 s at the median (2.0 to 2.6), the fastest measured | about $1 | daily use |
| Voice stays on your Mac (`voice-local`) | Anthropic (Gemini optional) | 30 of 35 audio checks, with Anthropic and Gemini keys; replies in 4.1 s at the median | about $0.40 (Anthropic and Gemini) | confidential work where text may leave the Mac but your voice may not |
| Fully local (`local`) | none | 10 of 19 one-session audio checks, every approval check among them; replies took 5.8 to 11.6 s | $0 | work where nothing may leave the Mac, on a 32 GB Mac |

Sources, speed and where your words go: [docs/setups.md](../../docs/setups.md).
<!-- end setups -->

`voice-local` downloads the local libraries and two models (about 2.3 GB, once; about a minute and a half on a fast
link). `local` downloads everything the fully local mode needs (about 8 minutes on a fast link) and starts the local
model: run that one in the background, as it outlasts a normal command, and tell them briefly what it prints. If it says
the Mac is not supported, offer Free start instead. Voice stays on your Mac hears and speaks on the Mac, so no recording
of their voice goes to any vendor; the brain is still Anthropic's Claude and gets text only. It cannot speak Hebrew,
and on laptop speakers interrupting it by voice takes 3 to 4 seconds, so recommend headphones. Fully local needs an
Apple-silicon Mac with 32 GB of memory or more, and about 19 GB of disk; it is free and private, and slower and less
accurate than the keyed setups, and it cannot speak Hebrew. What leaves the Mac is in the table's source,
docs/setups.md: say it in one line, and that they should use vendors their company allows.
</details>

If they ask about their Claude Pro or Max plan: Pointe cannot use the subscription, and adding it is not on offer.

**Step 3 of 4: your key.** For each key the setup needs and the doctor did not find, one at a time, say: "I'm opening
<vendor>'s key page in your browser, and a small Mac window. Create a key there, copy it, paste it in the window and
press Save. It goes straight into your Mac's Keychain, never into a file or this chat." Then run
`${CLAUDE_PLUGIN_ROOT}/bin/pointe key <vendor>` with a 10-minute timeout. It opens the page and the window itself, checks the key with one
tiny live call, opens the window again when the vendor refuses the key, saves it, and restarts Pointe if it runs. Read
its one line back. If it says "Cancelled", ask whether they want to try again. If the Mac asks whether Pointe may use
the Keychain item `pointe.<vendor>-api-key`, that is Pointe reading its own key: they press Always Allow, so it does not
ask at each start.

With a Gemini key on the free tier, add one line: when replies start to fail, the free quota is used up; they turn on
billing for the same key and change nothing else.

**Step 4 of 4: your first call.** Run `${CLAUDE_PLUGIN_ROOT}/bin/claude-voice-attach` with a 10-minute timeout. The first start takes up
to a minute, then a Chrome tab opens. If it says a key was refused, go back to step 3 for that key. Say exactly one
thing: "Put on headphones, allow the microphone, press Connect, and say hello." Then run
`${CLAUDE_PLUGIN_ROOT}/bin/claude-voice-attach heard 180` with a 4-minute timeout: it waits until Pointe has answered their first words.
When it says "Pointe heard you. You're set up.", say that line. If not, read them its one line of help and run it once
more.

**Done.** Run `mkdir -p ~/.claude-voice && touch ~/.claude-voice/setup-done` so new sessions stop suggesting setup.
Then three lines: which setup they have; `/pointe:voice` joins any other session to the call, `/pointe:stop` ends it;
`/pointe:doctor` shows what runs and the one thing to improve. Then, in one message, the optional extras, one line each:
"Optional, any time: your phone (`/pointe:setup phone`), the Mac app (`/pointe:setup apps`), or a faster setup (ask me
to show the setups)." Ask them to report anything confusing as an issue at github.com/ballerine-io/pointe.

## Optional extras

**Your phone.** The page works in the phone's browser; nothing to build. The phone needs a private way to reach this
Mac. Offer:
- Tailscale (easiest, free for personal use): install it on the Mac (tailscale.com/download) and the phone, sign in to
  the same account on both, then run `${CLAUDE_PLUGIN_ROOT}/bin/pointe pair tailscale`.
- Their company VPN, such as Twingate, if it routes to this Mac: run `${CLAUDE_PLUGIN_ROOT}/bin/pointe pair host <name>`.
- Same Wi-Fi only: `${CLAUDE_PLUGIN_ROOT}/bin/pointe pair wifi`.
Then `${CLAUDE_PLUGIN_ROOT}/bin/pointe pair link` prints an address that holds a secret: they open it once in the phone's browser (send
it to their own phone only, by AirDrop or Notes). The iPhone app is not in the App Store or on TestFlight yet; if they
build it (below), pairing shows a QR code to scan in the app. If the QR code does not show here, save it with
`${CLAUDE_PLUGIN_ROOT}/bin/pointe pair show` and open what it prints.

**The Mac app and the iPhone app.** Pointe has a Mac app (the call in the menu bar, no browser tab) and an iPhone app.
Neither has a download yet: each is built on this Mac with Xcode, by one command. Check Xcode first:
`ls /Applications | grep -i xcode`. If Xcode is missing, say it is a free, large (about 12 GB) install from the App
Store, that it is only for these two apps, and that they can come back to this later; do not push it on someone who is
not a developer. With Xcode there, run `${CLAUDE_PLUGIN_ROOT}/bin/pointe apps doctor` and read them what it found in plain words. It
never prints a Team ID.
- The Mac app needs no Apple Account: run `${CLAUDE_PLUGIN_ROOT}/bin/pointe apps mac --open` with a 15-minute timeout (the first build took
  under a minute in our clean run). It installs to ~/Applications and opens; its mark appears in the menu bar.
- The iPhone app needs an Apple Account signed in to Xcode (a free one is enough) and the iPhone connected. When the
  doctor says something is missing, walk them through its fix one step at a time; the steps are in Xcode's Settings and
  on the iPhone, never in a terminal. Then run `${CLAUDE_PLUGIN_ROOT}/bin/pointe apps ios` with a 15-minute timeout. Tell them: with a
  free account the app opens for 7 days, and the same command renews it; a plugin update keeps the same app and its
  pairing. When the fix is a `sudo` command (the Xcode license, `xcode-select`), do not ask them to type it: opening
  Xcode once accepts the license in a window, and Xcode's Settings, Locations, Command Line Tools selects Xcode.
- No iPhone or no Apple Account: `${CLAUDE_PLUGIN_ROOT}/bin/pointe apps ios --sim` shows the app in the Simulator.
If a build fails, read them the cause and the fix the command printed; the same table is in docs/phone.md, "Getting the
app". After the iPhone app is installed, pair it as above.
