# Security

Report a vulnerability through GitHub's private vulnerability reporting on this repository. Do not open a public issue.

## What Pointe is

A voice call into your Claude Code sessions. Words you speak can make a session do work, so a stranger who reaches the
daemon, or a web page that reaches it, must get nothing. The rules below are enforced in code and have tests, mostly in
`tests/test_security.py` and `tests/test_orchestrator.py`.

## Who may connect

- The daemon's HTTP port listens on the loopback interface only. Call audio uses the same port, as a WebSocket, so it
  never leaves loopback either. Only `pointe pair` opens another address (see Phone access).
- Every route except `/voice/health` needs a secret. Scripts send a per-daemon token (`~/.claude-voice/token`, 0600). The page
  opens once with a key in its address (`bin/voice-open`), which becomes an `HttpOnly`, `SameSite=Strict` cookie.
- That cookie lives on a private name, `<hash>.localhost`. Cookies ignore ports, so one set on plain `localhost` would reach any
  server you open on another port.
- `Origin` must match `Host` exactly, for HTTP and for WebSocket. This stops other web pages and DNS rebinding.
- Only the same origin can frame the page, which blocks clickjacking.
- An empty secret opens nothing.

## What a spoken word can do

With the default brain, a permission prompt is approved only when all of these hold:

- The daemon read the request out itself, from what will run and not from the description the session's model wrote.
  `readout.py` says a shell command only when every part of it is on an allowlist: known programs (`git`, `rm`, `cp`,
  `grep`, `curl`, `npm test`, `pytest`, ...), each with a table of known flags, in plain pipelines. It says every program,
  every file written, every URL's host, every git remote, and the flags that change what can be lost. Anything else
  (unknown programs or flags, `$`, backticks, globs, braces, subshells, heredocs, several lines, wrappers such as `sudo`
  or `env`, `VAR=` other than a few harmless ones, more than 25 words, or a credential-like value such as a key, a
  token or `password=`: `readout.redact`) is not read out. Two adversarial reviews found 24
  ways around earlier versions; each is now a test. File tools are read as their path. The line ends in "Should it?",
  with no consent word, so it cannot come back through the speakers as a yes.
- A request that is not read out is approved by a tap, never by voice: the page, and the phone app, show the exact
  request with Approve and Deny. A tap counts only for the request still pending. The terminal can answer it too.
- It was the last thing the bot said. No model wording can open this window, and any other speech closes it. So can being
  cut off. The request is then read out again.
- You said a yes and nothing else, begun after the read-out ended. "Okay, tell me more", "yes, and run the linter", "okay
  so", and "no worries" do not count.
- The yes came within 120 seconds of the read-out, on the active session.

The short form drops output-only flags and shortens paths plainly inside the project to their name. In our own Claude
Code history, about 13% of shell commands can be read out; the rest need a tap or the terminal.

Text-to-speech is not a proof. It can mispronounce a command, and you may not catch a dangerous flag by ear, so the page shows
the exact request. If you want no voice approvals, set `approvals: terminal`.

### Drive mode (optional)

Drive & walk mode (`drive.py`) only narrows the rules above; it never widens them. You enter it yourself ("drive mode",
"מצב נהיגה", or the Drive button); it is shown on the page and the phone, and it ends with the call (at once on a hang-up
or the idle timer; after 5 minutes when the link drops and does not come back). While it is on, a spoken yes approves a
request only when, on top of every rule above:

- the read-out allowlist can say it whole (a credential-like value is never read out: such a request waits for a tap);
- it loses nothing (`drive.road_safe`, its own allowlist): read-only programs, tests, `mkdir`, `touch`, `git status`,
  `diff`, `log`, `show`, `fetch`, `pull`, `add`, `commit`, `push` (no force, delete, mirror, `+ref` or `:ref`, no
  `--amend`, `--no-verify`, `--rebase` or `--prune`, no `add -f`, which adds what `.gitignore` keeps out), plain `curl` GETs, and edits inside the project. `rm`, `mv`,
  `cp`, redirects into files, `git reset`, `clean`, `rebase`, `checkout`, `stash`, `npm run`, `make`, `gh` and edits
  outside the project wait for a tap;
- with a voiceprint stored, the yes itself is a strong match for your voice (`speaker.strong`), at any lock level.

A no counts from any voice. A tap answers any request, as always: the page and the app hide the buttons while driving and
"I've stopped" leaves the mode, after which the request is read out again normally.

### Owner-voice lock (optional)

Settings → Voice lock learns your voice on a call and checks each thing said against it, on this Mac. Levels: **Off**
(as above), **Approvals** (a spoken yes counts only in your voice; a no counts from anyone), **Commands** (other voices
never reach the voice model; they are listed as ignored, with their words, in memory only), **Everything** (the same,
and their words are not shown or kept).

- **It only narrows.** A match is never consent: every rule above still has to hold for your yes. It adds "and it was
  your voice"; it removes nothing else.
- **It fails closed.** When it cannot tell (no model yet, a model error or a score slower than 0.6 s, under 0.3 s of
  audio, a damaged voiceprint), the speech counts as not yours for what the level guards. A tap, Face ID, the terminal
  and typed text still work, so this costs convenience, never control. Deleting the voiceprint turns the lock off.
- **It is not authentication.** It is a check against the bystander (a spouse, a colleague, a TV), not an attacker: a
  recording of your voice can pass it, and a short "yes" is weakly scored (it counts on its own only after a strong
  match within a minute, on the same device's voiceprint). Measured on synthetic voices only: see
  `bench/results/speaker.md`.
- **Model:** 3D-Speaker ERes2Net (Apache-2.0), run locally by `sherpa-onnx`, downloaded once from the sherpa-onnx
  GitHub release with a pinned SHA-256. No vendor sees the audio for this check or the voiceprint.

### Whisper mode

Whisper mode (`whisper.py`; "whisper mode", "מצב לחישה", or the Whisper button) changes how the call sounds, never what
a word can do. The bot plays at half volume, the microphone is raised (x2.5, soft limiter) with a whisper profile for
the voice detector, and replies are kept short. A whispered yes or no goes through exactly the same check as a spoken
one (tested by running the approval cases with the mode off and on and comparing the outcomes). It is never an
approval path and never lowers the voice lock: a voiceprint is learned from your normal voice, and a whisper scores
low against it (no synthetic whispered sentence reached the strong-match threshold in `bench/results/whisper.md`), so
with the lock on a whispered yes usually does not count and the request waits for a tap. Drive mode holds it: while
driving the bot plays at full volume and whisper mode applies again when drive mode ends. With a challenge on, both
apply; whisper mode adds nothing a challenge takes away.

### Audio briefings

A briefing ("brief me on the night", or scheduled) reads; it never sends or approves. Each part reaches the voice model
bracketed as data, with "send nothing, approve nothing"; a send still needs your fresh speech, and the briefing's own
words close the window for a spoken yes, so a yes after "lantern waits for your approval" brings the read-out again
instead of approving. A permission is named in a briefing ("a permission approval"), never quoted. Credentials are
masked with the same rule as the read-out and the alerts (`readout.mask`) before a session's record reaches the reading
model, and again on what it writes. No briefing is spoken during a meeting or brainstorm; a meeting that starts stops it.

A realtime front (`CLAUDE_VOICE_FRONT=gemini` or `openai`) speaks by itself, so there is no line to bind a yes to: it can deny
by voice, but only the terminal approves.

What sessions report is data for the voice model, not instructions to it:

- A model gate checks each new send against what you just said. The gate is a model and can be wrong. It lowers the risk of
  prompt injection, it does not remove it.
- A correction ("no, the other session") or a yes to "which session?" skips the gate, and sends the earlier text word for
  word, whatever the model wrote.
- A request reaches another session only if you said its name, or said yes to a question that named it.
- `ask_about_session` has no gate. It only reads, and the answer goes to the speaker.

## Keys

- Keys come from the environment or the macOS Keychain, and reach the daemon only.
- Claude Code sessions never receive them from Pointe, and `git` runs without them.
- They are not in command lines: scripts pass the token to `curl` through `--config`.
- The page shows vendor errors with key values replaced. Logs hold an error's text as the vendor wrote it.

## What leaves your machine

| What | Where |
|---|---|
| Your speech, and your dictionary, session and folder names and the names in session notes as hints | The ears vendor |
| Session content, including transcripts | The brain and reader vendors |
| What the bot says, which can quote session content | The mouth vendor |
| What you said, each session's latest lines, goal, folder path and up to 40 file names | The gate vendor |

With the microphone set to push to talk (Settings, on the page or the phone), no audio leaves your machine unless you hold
the talk control (or toggled it on), plus 0.4 s after you let go. The daemon enforces this: it drops the audio before the
voice detector and every vendor, whatever a client sends. A press ends by itself after 90 s. One exception: during a
meeting you started (it asks for consent and shows a recording indicator), the room's audio goes to the meeting's speech
vendor without a press; talking to Pointe outside the meeting stream still needs one.

In fully local mode (`pointe local`), none of these goes anywhere: no key is read, from the environment or the
Keychain, so no vendor can be reached, and the text-model server listens on loopback only. See
[docs/features/local.md](docs/features/local.md).

With "Voice stays on your Mac" (`pointe local voice`), no audio goes to a vendor: ears and mouth run on the Mac, the
Soniox and ElevenLabs keys are never read, meeting mode is off, and every path that would stream audio out (cloud ears or
mouth, a realtime front, the echo guard's mirror stream, meeting ears) is refused in code. The brain, reader and gate
vendors still receive text. See [docs/features/voice-stays-local.md](docs/features/voice-stays-local.md).

Choose vendors you are allowed to send that content to. `bin/voice-doctor` shows which ones are in use. Pointe has no server
and no telemetry, and the page loads nothing from outside your machine.

## Files

`~/.claude-voice` is 0700. It holds the token, the page key, session notes, `daemon.log`, and `journal.jsonl`, a full record of
each call with what you said and session content. With phone access it also holds the pairing secret, a TLS key and the
connector's tokens. With the voice lock it holds `voiceprint/` (0700; one file per enrolled device, 0600): biometric data,
computed and kept only on this Mac, deleted from Settings → Voice lock on the page or in the app. `models/` holds the
speaker model. With fully local mode, `local/` holds the text-model server's environment, its log (which may hold session
content in errors) and `config.before-local.json`, the choice `pointe local off` restores; the models themselves sit in
the Hugging Face cache (`~/.cache/huggingface`) and Kokoro's in `~/.cache/pipecat`. The journal records an ignored utterance's length and score, never its words. `briefings.json` (0600) keeps
the last seven briefings, written out per session and redacted. `dictionary.json` (0600) holds the names you added or
fixed (Settings → Dictionary on the page or in the app shows, edits and deletes each one); it never takes a yes, no or
stop word, anything `readout.mask` would hide, or words from a meeting. Delete what you no longer need.

## Known limits

- **Code running as you is trusted.** It can read the token and forge anything: register a session, read the journal, inject a
  prompt, or approve a permission prompt through a session's channel. Claude Code's child processes receive the token in launch
  mode. Pointe does not defend against code already running as you; a separate OS user would.
- **Launch mode uses `--dangerously-load-development-channels`.** Claude Code requires this flag for a channel outside its
  allowlist. It loads only `channel/voice-channel.mjs` from this repository, and Claude Code shows a warning at start.
- **A spoken yes in conversation is not an approval.** See the [safety model](README.md#safety-model) in the README. Permission prompts are different: they are answered through Claude Code's `PermissionRequest` hook, and its deny rules still apply.
- **Voice is not authentication.** Anyone your microphone can hear can answer a prompt, unless the voice lock is on; even
  then, a recording of your voice can pass it.
- **The page key does not rotate by itself.** It lasts until you delete `~/.claude-voice/page_key`. It also passes through a
  browser's command line when `bin/voice-open` runs, which other users on a shared Linux machine can read.
- **While the voice holds a prompt, the terminal also shows it**, and either can answer. It waits up to 280 seconds. If you answer in the terminal, the daemon may not notice at once, because of how it reads a closed connection (Low; a known limit).
- **Two pages with the key can both be in a call.** Keep it to one.

## Phone access (experimental, off by default)

`bin/voice-remote` adds an HTTPS listener for a phone on a private network. Remote requests need the configured name and a
pairing cookie. The listener is decided by the port that accepted the connection, never by `Host` or forwarded headers.
Limits: the pairing link is a lasting secret with no rotate command, despite the word "link", so treat it as a password. `bin/voice-remote off` leaves the connector and its tokens in place. And `bin/voice-connector` pulls
`twingate/connector:1`, a moving tag. Call audio over this path is one TCP connection.

### The iPhone app

- **Pairing.** `pointe pair tailscale|wifi|host <name>` makes a TLS certificate for that one name, and a QR code with its
  SHA-256 and the phone's own key (`phone_key`, 0600). The app keeps both in the Keychain and talks only to that Mac.
- **Pinning, and App Transport Security off.** The app accepts exactly the certificate it paired with, and nothing else,
  CA-signed or not. iOS's App Transport Security can't be scoped to a name you pick (a Twingate or VPN name), and it
  refuses a self-signed certificate before the app's own check runs, so it is off for this app. The pin is the stronger
  check: ATS trusts any CA-issued certificate for the name, and the pin trusts one certificate.
- **What the phone key opens:** the call socket, status (sessions, the last turns of the conversation, the words being
  heard), approve, "just listen", switching the active session, hanging up, and the voice lock (`/voice/voiceprint`:
  enrol, delete, level; the app asks for Face ID before lowering the level or deleting), briefings (`/voice/briefings`:
  the last seven, start, skip, stop, and the schedule), Show while it says (`/voice/artifact`), the dictionary (`/voice/dictionary`: list, add, edit, delete), drive mode (`/voice/drive`: on, off), and the conflict alarm (`/voice/conflicts`: dismiss,
  or ask one side as typed words, which never approve). Not the model's whole context, renaming, modes, or anything a Claude Code session uses.
- **Show while it says reads source files.** The page on this Mac always shows the files and test output the voice talks
  about. The phone key, and a page opened over the TLS listener, get nothing (no `showing` in status, 403 from
  `/voice/artifact`) until `show.on_phone` is on (Settings → Show while it says; the app asks for Face ID to turn it
  on). Once on, a leaked phone key can read what the voice showed: the last ten reports' files, inside each session's
  folder only. Either way the daemon never takes a path from the caller, shows only tools that ran (never a tool still
  waiting for approval), refuses files outside the session's folder after resolving symlinks, hidden files and
  secret-looking names (`.env*`, `*.pem`, `*secret*`, `*key*`, `id_*`, `*credential*`, ...), binary files and files over
  512 kB, and masks secret-looking values (known token shapes, private keys, `name = "..."` and unquoted `name: value` for secret-like names, URL
  passwords, and the values of this machine's own key variables) in file lines, diffs, test output and commands.
  Diffs read `HEAD` with `git cat-file`, never `git diff`, so a repository's filters and diff drivers do not run.
- **Approve needs Face ID** or the passcode; deny never does. One opt-in exception: with "Approve from notifications"
  on (`alerts.watch_approve`, off by default; the app asks for Face ID to turn it on), a notification's Approve needs an
  unlocked iPhone or a watch on the wrist instead. The daemon accepts it (`via: "notification"`) only for a request it can
  read out, bound to that request's id (`alerts.py`).
- **Notifications** (phone, watch, desktop) show only the read-out form of a request, never its full text or the model's
  description; a request that cannot be read out shows only its tool. Credential-like values follow the same rule as
  the voice (`readout.redact`): never shown, never said.
- **Revoke:** delete `~/.claude-voice/phone_key` and restart the daemon. Pairing again with the same name keeps the
  certificate, so a browser that trusts it keeps working.
- Tested on a real iPhone over Twingate, and in the simulator against a real host name.
