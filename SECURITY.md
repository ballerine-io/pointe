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
  or `env`, `VAR=` other than a few harmless ones, more than 25 words) is not read out. Two adversarial reviews found 24
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
| Your speech, and your session and folder names as hints | The ears vendor |
| Session content, including transcripts | The brain and reader vendors |
| What the bot says, which can quote session content | The mouth vendor |
| What you said, each session's latest lines, goal, folder path and up to 40 file names | The gate vendor |

Choose vendors you are allowed to send that content to. `bin/voice-doctor` shows which ones are in use. Pointe has no server
and no telemetry, and the page loads nothing from outside your machine.

## Files

`~/.claude-voice` is 0700. It holds the token, the page key, session notes, `daemon.log`, and `journal.jsonl`, a full record of
each call with what you said and session content. With phone access it also holds the pairing secret, a TLS key and the
connector's tokens. Delete what you no longer need.

## Known limits

- **Code running as you is trusted.** It can read the token and forge anything: register a session, read the journal, inject a
  prompt, or approve a permission prompt through a session's channel. Claude Code's child processes receive the token in launch
  mode. Pointe does not defend against code already running as you; a separate OS user would.
- **Launch mode uses `--dangerously-load-development-channels`.** Claude Code requires this flag for a channel outside its
  allowlist. It loads only `channel/voice-channel.mjs` from this repository, and Claude Code shows a warning at start.
- **A spoken yes in conversation is not an approval.** See "Approvals" in the README. Permission prompts are different: they are answered through Claude Code's `PermissionRequest` hook, and its deny rules still apply.
- **Voice is not authentication.** Anyone your microphone can hear can answer a prompt.
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
  heard), approve, "just listen", switching the active session, and hanging up. Not the model's whole context, renaming,
  modes, or anything a Claude Code session uses.
- **Approve needs Face ID** or the passcode; deny never does.
- **Revoke:** delete `~/.claude-voice/phone_key` and restart the daemon. Pairing again with the same name keeps the
  certificate, so a browser that trusts it keeps working.
- Tested on a real iPhone over Twingate, and in the simulator against a real host name.
