# Security

Report a vulnerability through GitHub's private vulnerability reporting on this repository, or by email to
security@ballerine.com. Do not open a public issue.

## What Pointe is

A voice call into your Claude Code sessions. Words you speak can make a session do work, so a stranger who reaches the
daemon, or a web page that reaches it, must get nothing. The rules below are enforced in code and have tests, mostly in
`tests/test_security.py` and `tests/test_orchestrator.py`.

## Who may connect

- The daemon's HTTP port listens on the loopback interface only, on both addresses: `127.0.0.1` and `[::1]`
  (`guards.loopback_sockets`; the node does the same). A browser tries `::1` first for `localhost` and
  `<hash>.localhost`, so a program of another user on `[::1]:7860` beside a daemon on `127.0.0.1` alone would be handed
  the page key. With both held nobody else can take either, and a daemon that finds either taken does not start. A
  machine with no IPv6 loopback at all listens on `127.0.0.1` alone; there no one can take `::1` either. Call audio
  uses the same port, as a WebSocket, so it never leaves loopback either. Only `pointe pair` opens another address
  (see Phone access).
- Every route except `/voice/health` needs a secret. Scripts send a per-daemon token (`~/.claude-voice/token`, 0600). The page
  opens once with a key in its address (`bin/voice-open`), which becomes an `HttpOnly`, `SameSite=Strict` cookie.
- A script sends the token or the page key only when the program listening on the port is the one the daemon's pid file
  names, or its child (`bin/voice-ours`): with the daemon down, another user's program on `127.0.0.1:7860` gets nothing.
  Where nothing can tell who listens (no `lsof`, `ss` or `/proc`), nothing is sent.
- That cookie lives on a private name, `<hash>.localhost`. Cookies ignore ports, so one set on plain `localhost` would reach any
  server you open on another port.
- `Origin` must match `Host` exactly, for HTTP and for WebSocket. This stops other web pages and DNS rebinding.
- Every POST must say `Content-Type: application/json`, on this port and on the phone's listener, or it gets 415. A page
  on another origin can send a POST without asking first only as text, a form or an empty body, so none reaches a
  route. The check runs after the secret check.
- Only the same origin can frame the page, which blocks clickjacking.
- The page runs only the scripts it was served with. Its `Content-Security-Policy` lists the SHA-256 of each inline
  script and event handler, computed from the page when it is served (`guards.page_csp`), on both listeners; a script
  or handler that reaches the page later matches none and does not run. Plugins and `<base>` are refused. The rest of
  the policy keeps injected markup from sending data out: fetches and the call's WebSocket go only to the page's own
  origin, images only to it or `data:`, media to it or `blob:`, and forms post nowhere else. The page
  builds session names, machine names and the QR code as nodes, never by parsing HTML. Browsers older than about 2022
  (Safari before 15.4) do not support hashed handlers and would refuse the page's buttons.
- An empty secret opens nothing.

## What a spoken word can do

A new Claude Code session that Pointe starts skips permission prompts by default (see [Starting a
session](#starting-a-session)). In such a session there is no prompt to approve: what a spoken request asks for, the
session can do without asking. The rules below apply to every session that asks: sessions you join, sessions you
reopen, and new sessions under Ask before actions.

With the default brain, a permission prompt is approved only when all of these hold:

- The daemon read the request out itself, from what will run and not from the description the session's model wrote.
  `pointe/readout.py` says a shell command only when every part of it is on an allowlist: known programs (`git`, `rm`, `cp`,
  `grep`, `curl`, `npm test`, `pytest`, ...), each with a table of known flags, in plain pipelines. It says every program,
  every file written, every URL's host and path, every git remote whole (a URL path over 60 characters makes the request
  unreadable), and the flags that change what can be lost. A `cd` counts only when `&&` follows it: `cd x ;`, `cd x ||`,
  a pipe into or out of a `cd`, an `||` before one, or a `;` or `||` anywhere after one makes the request unreadable,
  because what follows can run where the session started. A command that Claude Code's hook or Codex reports running in
  another folder than the session's (an earlier `cd` persists in Claude Code's shell; Codex picks a folder per command)
  starts with "in" and that folder, and its paths are said from there; for a session on this Mac the card shows the
  folder too. Launch mode's channel and OpenCode do not report the folder: there, paths are said from the session's
  folder. A quoted
  argument is said as it is when it is a plain word or path, and as "some text" only when it is a `grep` or `rg`
  pattern or what `echo` prints; a quoted flag, or any other quoted argument, makes the request unreadable, as does a
  flag whose value is missing (`git commit -m ; rm x`). A path whose real location (through a symlink) leaves the
  project is said in full. Anything else
  (unknown programs or flags, `$`, backticks, globs, braces, subshells, heredocs, several lines, wrappers such as `sudo`
  or `env`, `VAR=` other than a few harmless ones, more than 25 words, or a credential-like value such as a key, a
  token or `password=`: `readout.redact`) has no short form. Two adversarial reviews found 24
  ways around earlier versions; each is now a test. File tools are read as their path. The line ends in "Should it?",
  with no consent word, so it cannot come back through the speakers as a yes.
- Everything can be approved by voice, and nothing that was not said in full (the owner's rule since 1.30.0). A request
  with no short form is read word for word (`guards.verbatim_request`): "run, word for word:" and the exact command, or
  each argument of another tool, with format and control characters named ("hidden character 202E"), in parts of 18
  words with a pause between. A yes after it approves exactly those words, under every rule below. A long one (over 40
  words read, or a command of more than 64 characters: about five seconds aloud) is first sent back to the session once
  for plain commands, which are easier to follow by ear, at most twice in ten minutes; after that it is read word for
  word. A read-out is read once: its reminder is one line ("billing's still waiting on your yes
  or no"), and "read it" brings the request again. A yes after the reminder approves the request when it is the only
  one waiting, it was read in full, and nothing but the reminder was said since its read-out (the owner's rule: a plain
  yes after a full read-out approves what was read, without friction); "Approved." confirms it. In any other case
  (another request waiting, anything else said since, a read-out the user cut) a yes brings the request again before
  anything is approved. Drive mode does not read one out: it waits until you stop.
- A request re-aimed at another session ("no, I meant quarry, not billing") is taken back from the first: Pointe tells
  it to drop that work and make no changes for it, and says no to a permission it asked for since the request reached
  it. Pointe never approves on its own; a no is safe (at worst the session asks again). A request it was waiting on
  before then is left alone.
- A command that only looks is said as that: "look around, read only: pwd, ls, git status, grep and find", and "also
  in /tmp" when it looks outside the project or at a hidden or secret-looking file (`readout.looking`); a project next
  to this one is said by its name ("also in tariff-api, next to the project") and "/" as "the whole disk". A session
  exploring a project asks for long lists of these, and word for word one took 38 seconds. The list of what only
  looks is its own allowlist and a narrow one: known reading programs, git's reading subcommands, find with no action,
  no redirect but to `/dev/null`, no substitution, no variable but `$?` and `$PWD`, no background job. Its patterns and
  flags are not said; every program and every place outside the project is. Each way around it found so far is a test
  (`tests/test_readout_looking.py`), and anything it does not know is read word for word.
- One kind is never said: a request with a secret written in it (a key, a token, `password=`: `readout.redact`). Said
  aloud, the secret would reach the speech vendors; masked, it would be approved unheard. On a call it is sent back to
  the session to pass the secret by reference (an environment variable or a file), which can then be read out; if the
  session does not, the request waits for a tap. A question to the user (Claude Code's AskUserQuestion, ExitPlanMode)
  takes an answer, not a yes.
- The page, and the phone app, show the exact request with Approve and Deny. The card leads with what runs (the tool and its input); the description the session's
  model wrote is a separate line, at most 200 characters, marked as the agent's note on the page. Format and control
  characters (bidi overrides, zero-width spaces) are shown as `\uXXXX`. A request that reached Pointe cut short (a
  preview that does not parse) is marked so, and a tap can only deny it: approve it in its terminal. A tap counts only
  for the request still pending. The terminal can answer it too.
- It was the last thing the bot said. No model wording can open this window, and any other speech closes it. So can being
  cut off, or a change of the active session (a click, or the active session leaving). The request is then read out
  again.
- You said a yes and nothing else, begun after the read-out ended. "Okay, tell me more", "yes, and run the linter", "okay
  so", and "no worries" do not count.
- The yes came within 120 seconds of the read-out, on the active session. A yes with more words after it ("okay, yes,
  run the tests") once the request went cold brings the read-out back; it approves nothing.

The voice never passes a yes on in words: a message to a session that vouches for the user's yes to a delete, a push, a
merge or a post ("the owner confirms by voice: yes, delete…") is refused in code, whether or not that session has asked
for one (`owner_yes_relay`). And the model may not say a waiting request was approved or is running.

The short form drops output-only flags and shortens paths plainly inside the project to their name. A command without
one is read word for word.

Text-to-speech is not a proof. It can mispronounce a command, and you may not catch a dangerous flag by ear, so the page shows
the exact request. If you want no voice approvals, set `approvals: terminal`.

### Starting a session

Pointe can start a new coding-agent session (`docs/features/new-session.md`). It is the one thing a spoken word can do
that creates a process, so it is fenced on every side, in code with tests (`tests/test_new_session.py`):

- **Where.** Only in a folder from a list the daemon builds: folders of the sessions on the voice, of sessions that
  joined in the last 30 days, and folders added in Settings. A request's folder is looked up in that list; a path is
  never trusted, from speech, the page or the phone. `sessions.folders` is refused from the phone's key and from a page
  opened over the network, so the list grows only at the Mac.
- **How: new Claude Code sessions skip permission prompts by default.** Decided 2026-11-25 by the owner of Pointe,
  for everyone and for the public release, after hearing the risk and the alternative. **The risk: such a session can
  edit, delete and overwrite files, run any command and reach the network without asking, and a prompt injection in
  what it reads acts with the same freedom.** Claude Code's own warning applies: bypass mode offers no protection
  against prompt injection or unintended actions. The setting "Permissions for new sessions" (`sessions.permissions`)
  turns it off for every new session (Ask before actions), and "start a session that asks first" turns it off for one.
  Its pieces, each in code with a test (`tests/test_skip_permissions.py`):
  - The flag is `--permission-mode bypassPermissions` (`claude_code.SKIP_ARGS`), the mode
    `--dangerously-skip-permissions` also selects. Only for a new Claude Code session: a reopen, a night shift's new
    session, Codex and OpenCode never skip, and `harnesses.base.refuse_bypass` still checks every other part of every
    command line and request a starter builds. A Codex thread that would run with no approvals and no sandbox is
    archived and refused (`harnesses.codex.bypasses`). `pointe start` (`bin/claude-voice`) refuses every skip flag and
    setting before it starts anything.
  - Claude Code asks once, in its terminal, before a session first skips prompts. Pointe never answers that for the
    user without their yes and never writes their Claude Code settings: it reads whether the check was accepted
    (`claude_code.skip_check`), and when it was not, the read-back asks for consent plainly and a yes is kept in Pointe's
    own settings (`sessions.skip_ok`, which no request can set). The yes reaches Claude Code only in that session's
    `--settings` file. The New session sheet cannot show the question, so a start from it that still needs the yes
    asks before actions. Should Claude Code end before its session starts, the start script runs it again asking.
  - The same per-session settings set `crossSessionInbound` to `accept`: Claude Code holds every message to a session
    that skips prompts unless it does, and the voice's requests arrive as such messages. That session therefore also
    takes, without a prompt, a message from another of your Claude Code sessions.
  - Turning skipping on by voice ("new sessions skip permission prompts") needs the owner's voice when the voice lock
    is on; turning it off counts from any voice. The read-back, the yes and Face ID or Touch ID for a start are as
    below.
- **Plugin commands.** A command file's `allowed-tools` lets the model run those commands without a prompt for that
  turn, in a session that may have read a stranger's text. Each rule names one command the file tells the model to run
  (`pointe setup`, `pointe key`, `pointe apps doctor`, ...), never `pointe` itself, `open` or `echo`; `pointe start`,
  `pair`, `hub`, `join` and `uninstall` always ask (`tests/test_plugin_permissions.py`). `/pointe:voice`, which runs on
  every join, pre-approves only joining (`claude-voice-attach`, `voice-first-run`, `pointe node status`); on a first run
  it says to run `/pointe:setup`, which carries setup's own list.
- **Who.** By voice, always a read-back of the agent, folder, machine and name, taken from the user's own words, then a
  plain yes within 60 seconds, under the rules of a yes to a permission prompt (`daemon._readback_answer`): a yes and
  nothing else, begun after the read-back ended, with the read-back the last thing the bot said; not the read-back
  heard back, not typed or corrected words, and with the voice lock on only the owner's voice. The read-back ends in a
  question with no consent word in it. A realtime front words the read-back itself, so there it takes a tap. That yes never approves a waiting request. On the iPhone and the Mac app, Start asks for Face ID or
  Touch ID. Meeting mode and Challenge me cannot start anything.
- **Left open.** Code running as you can register a session from any folder (it could before), which makes that folder
  "recent". A paired phone can start a session with a first prompt in an allowed folder, and with the default setting
  that session acts on the prompt without asking; the phone could already send requests to the sessions there.

### Adding sessions

Pointe can join sessions the user already runs, and reopen one they ran this week, from a description
(`docs/features/add-sessions.md`). Joining gives the voice that session's transcript, sends and (where the harness
allows) its approvals, so it is fenced the same way as a start, in code with tests (`tests/test_attach_*.py`):

- **Who.** By voice, nothing joins on the first sentence: Pointe reads back what it found, from the user's own words,
  and joins on a plain yes within 60 seconds, or on a pick from the list it read back ("the second one", "both"), bound
  to exactly those sessions, both under a start's rules (the read-back the last thing said, begun after it). Not the
  read-back heard back, not typed words, and with the voice lock on only the owner's
  voice; that yes never approves a waiting request. On a screen, a tap sends back a key from the Mac's own listing
  (never a path), and on the iPhone and the Mac app Join and Reopen ask for Face ID or Touch ID. Meeting mode and
  Challenge me cannot add sessions.
- **Whose.** Only this OS user's: the config dirs Pointe knows that the user owns, processes the daemon may signal, and
  inbox sockets that are sockets owned by the user and not links. Claude Code's inbox socket is read from its own record
  of the process (`sessions/<pid>.json`), checked against the session `claude agents --json` names.
- **Reopen.** A Claude Code session reopens with `claude --resume <id> --permission-mode default` in a new terminal
  window, never with a skip flag; a Codex thread that comes back with no approvals and no sandbox is refused.
- **Approvals.** A Claude Code session whose Pointe plugin was not on when it started keeps its prompts in its terminal;
  Pointe says so in the read-back and never claims otherwise.
- **Left open.** Code running as you could already register any of your sessions; a paired phone can now add any of
  your sessions listed on the Mac, after Face ID. Discovery reads up to 64 KB from each end of a week of transcripts.

### Night shift

A night shift (`docs/features/night-shift.md`) is the one time Pointe sends to sessions while nobody is listening, so
its rules are code with tests (`pointe/nightshift.py`, `tests/test_night_shift.py`):

- **It starts on your yes.** The sessions and tasks are cut from your own words, read back with the caps, and started
  on a plain yes within 60 seconds, under the rules of a new session's yes. On a screen, Start shift is its own button;
  the apps ask for Face ID or Touch ID.
- **Pointe never answers an approval.** A permission request from a session on the shift is held, neither allowed nor
  denied, for up to 12 hours, and recorded word for word in the ledger. It is answered only by you: the read-out and
  your yes, a tap, or the session's own terminal. No function of the shift can reach the code that delivers a verdict
  (tested by reading the source).
- **Every message is a fixed template** around your own task. No model writes a send at night. Each one repeats that
  nothing destructive or outward-facing beyond the task may be done.
- **Nothing is widened.** No permission mode or allow rule changes; a new session on the plan passes New session's
  checks.
- **Caps and stop.** 8 hours and 40 messages by default, at most 12 and 200. "Stop the night shift" counts from any
  voice, as a no does; it only ends sending.
- **Left open.** A session told to "choose the most defensible answer" makes judgment calls you did not see: they are
  on the ledger with what changes otherwise, and the briefing leads with them. A paired phone can start a shift, as it
  can already send requests. `hooks/hooks.json` lets the permission hook wait 12 hours (it was 5 minutes): the daemon
  still lets an ordinary request go after 280 seconds, and a daemon that stops drops the connection.

### Drive mode (optional)

Drive & walk mode (`pointe/drive.py`) only narrows the rules above; it never widens them. You enter it yourself ("drive mode",
"מצב נהיגה", or the Drive button); it is shown on the page and the phone, and it ends with the call (at once on a hang-up
or the idle timer; after 5 minutes when the link drops and does not come back). While it is on, a spoken yes approves a
request only when, on top of every rule above:

- the read-out allowlist can say it whole (a credential-like value is never read out: such a request waits for a tap);
- it loses nothing (`drive.road_safe`, its own allowlist, of programs and of each program's flags: a flag the read-out
  does not know for that program waits, as do git's `--upload-pack`, `--receive-pack`, `--exec` and `-c`, curl's data
  and config flags, and `uniq` with an output file): read-only programs, tests, `mkdir`, `touch`, `git status`,
  `diff`, `log`, `show`, `fetch`, `pull`, `add`, `commit`, `push` (no force, delete, mirror, `+ref` or `:ref`, no
  `--amend`, `--no-verify`, `--rebase` or `--prune`, no `add -f`, which adds what `.gitignore` keeps out), plain `curl` GETs, and edits inside the project. `rm`, `mv`,
  `cp`, redirects into files, `git reset`, `clean`, `rebase`, `checkout`, `stash`, `npm run`, `make`, `gh` and edits
  outside the project wait for a tap, as does any edit in a session on another machine (its folder is not on this disk);
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
- **Only the owner adds a voiceprint.** The first one can be enrolled from anywhere. Once one is stored (damaged
  counts), the phone key and a page opened over the TLS listener can start another only within a minute of a strong
  match to it on the call, at any level: with the lock off a voiceprint still guards drive mode's yes, and it counts
  as soon as the lock goes up. The page on this Mac is not limited. The apps also ask for Face ID first.
- **Meetings.** The meeting's owner is the one whose addressed words act (end the meeting, ask a session, speak to the
  room). With a voiceprint, a turn that strongly matches it binds the owner. Without one, a label is all Pointe has, so
  only the speaker of the words that started the meeting, or a tap on "That was me", becomes the owner; "Pointe, that's
  me" by voice never takes the seat, empty or held, before or after the room's stream reconnects. Left open: the
  speech vendor can file a guest's turn under the owner's label, and with no voiceprint nothing catches that. When the
  owner asks Pointe for its view, the room's words reach that turn as data; the brain may look up a session only if the
  owner's own question names it, and a copy's answer passes `readout.mask` before the room or the notes get it.
- **It is not authentication.** It is a check against the bystander (a spouse, a colleague, a TV), not an attacker: a
  recording of your voice can pass it, and a short "yes" is weakly scored (it counts on its own only after a strong
  match within a minute, on the same device's voiceprint). Measured on synthetic voices only: see
  `bench/results/speaker.md`.
- **Model:** 3D-Speaker ERes2Net (Apache-2.0), run locally by `sherpa-onnx`, downloaded once from the sherpa-onnx
  GitHub release with a pinned SHA-256. No vendor sees the audio for this check or the voiceprint.

### Whisper mode

Whisper mode (`pointe/whisper.py`; "whisper mode", "מצב לחישה", or the Whisper button) changes how the call sounds, never what
a word can do. The bot plays at half volume, the microphone is raised (x2.5, soft limiter) with a whisper profile for
the voice detector, and replies are kept short. A whispered yes or no goes through exactly the same check as a spoken
one (tested by running the approval cases with the mode off and on and comparing the outcomes). It is never an
approval path and never lowers the voice lock: a voiceprint is learned from your normal voice, and a whisper scores
low against it (no synthetic whispered sentence reached the strong-match threshold in `bench/results/whisper.md`), so
with the lock on a whispered yes usually does not count and the request waits for a tap. Drive mode holds it: while
driving the bot plays at full volume and whisper mode applies again when drive mode ends. With a challenge on, both
apply; whisper mode adds nothing a challenge takes away.

### Mute

Mute (`pointe/mute.py`; the speaker button beside the status line, or "stop talking, I'll read") stops the voice: no line
reaches the mouth, so nothing is synthesised, and every line is shown as text. It never widens what a word can do.
Approvals and read-backs keep their rules: a tap, or a spoken yes begun after the line appeared with nothing said
between; a typed yes confirms nothing, since a tap in the apps asks for Face ID or Touch ID (tested unmuted and muted,
outcomes compared). Drive mode holds it. `POST /voice/read`, which an app from before the mute button still calls, only
marks lines read.

### Session mode

Session mode speaks about the session in focus only (`pointe/scope.py`): the other sessions' reports, joins, conflict alarms,
machine drops and approval requests are held for the screens and never spoken, and the brain is not told their state.
An approval held this way loses nothing: its card stays tappable, alerts still raise it, and one wordless chime marks it.
`POST /voice/held` has the held news said; it approves nothing.

### Audio briefings

A briefing ("brief me on the night", or scheduled) reads; it never sends or approves. Each part reaches the voice model
bracketed as data, with "send nothing, approve nothing"; a send still needs your fresh speech, and the briefing's own
words close the window for a spoken yes, so a yes after "lantern waits for your approval" brings the read-out again
instead of approving. A permission is named in a briefing ("a permission approval"), never quoted. Credentials are
masked with the same rule as the read-out and the alerts (`readout.mask`) before a session's record reaches the reading
model, and again on what it writes. No briefing is spoken during a meeting or brain dump; a meeting that starts stops it.

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

- Keys come from the environment or the macOS Keychain, and reach the daemon only. A key read from the Keychain stays in
  the daemon's memory, never in its environment.
- No program Pointe starts receives them: not `claude agents`, `git`, OpenCode, the local text-model server or any other
  tool. Each gets the daemon's environment without the key variables (`pointe/childenv.py`; `tests/test_child_env.py`
  fails on a spawn that does not use it). The exceptions start the daemon itself (`pointe key`'s restart, `pointe
  join`), which reads keys from the environment it is given; `pointe apps` and `pointe uninstall` never read a key and
  pass on the environment your shell gave them.
- One exception, for one key: the `claude -p` copy a side question or an overview runs in starts without any key, and
  signs in as the session's account does. A session that runs on an `ANTHROPIC_API_KEY` leaves that copy nothing to
  sign in with ("Not logged in"); it is then started once more with Pointe's own Anthropic key and no other. The copy
  has no settings, hooks or MCP servers and can only read files (`--permission-mode dontAsk`), so it cannot run a
  command that would print the key or send it anywhere (`harnesses/claude_code.py`, `side_question`).
- Pointe saves each key as `pointe.<vendor>-api-key`. It still reads the names of pre-release builds (`openai-api-key`,
  `gemini-api-key`, ...) after its own, so a key saved then keeps working. Another tool may keep an item under such a
  name: Pointe then uses that key for the same vendor, and `pointe key <vendor>` saves one of Pointe's own, which wins.
  With `openai_url` set, only `pointe.openai-api-key` is read from the Keychain, so another tool's item there never goes
  to that host (`OPENAI_API_KEY` in the environment still comes first).
- **Any program running as you can read them.** Pointe saves and reads the Keychain items through macOS's own
  `/usr/bin/security`, so the item's access list names that tool, not Pointe: a program running as you can run
  `security find-generic-password -s pointe.<vendor>-api-key -w` and get the key, without a prompt. Pressing Always
  Allow when macOS asks (`/pointe:setup`, step 3) also allows `security`. This is the known limit below, code running as
  you is trusted; the Keychain keeps the keys off disk in plain text and out of other users' reach.
- They are not in command lines: scripts pass the token to `curl` through `--config`.
- The page shows vendor errors with key values replaced. Logs hold an error's text as the vendor wrote it, and a
  traceback without the values of its variables: the daemon and the node turn loguru's `diagnose` off, which would
  print a key or a URL with `?key=` (`tests/test_log_tracebacks.py`).

## What leaves your machine

| What | Where |
|---|---|
| Your speech, and your dictionary, session and folder names and the names in session notes as hints | The ears vendor |
| Session content, including transcripts | The brain and reader vendors |
| What the bot says, which can quote session content | The mouth vendor |
| What you said, each session's latest lines, goal, folder path and up to 40 file names | The gate vendor |
| When you add sessions by voice and a few fit about as well: each one's title, folder name, age and up to 8 keywords (at most 8 sessions, never a transcript) | The gate vendor |

With the microphone set to push to talk (Settings, on the page or the phone), no audio leaves your machine unless you hold
the talk control (or toggled it on), plus 0.4 s after you let go. The daemon enforces this: it drops the audio before the
voice detector and every vendor, whatever a client sends. A press ends by itself after 90 s. One exception: during a
meeting you started (it asks for consent and shows a recording indicator), the room's audio goes to the meeting's speech
vendor without a press; talking to Pointe outside the meeting stream still needs one. On the iPhone, Talk to Pointe
(the Action button, a Control in Control Center or on the Lock Screen, the Home Screen widget, Back Tap, Siri) is a
press too. It opens the app, so on a locked phone iOS asks for Face ID or the passcode before anything listens; with no
call up it starts one, to the orchestrator. The call's Live Activity on the Lock Screen (Send, Cancel, Hang up) works
without unlocking while a call is up, by design: anyone next to the locked phone can send or end a press you opened. Its
Talk opens the app, and so needs the unlock. No part of this path approves anything (`tests/test_widget.py`). Settings
→ Talk from outside the app turns the start off.

In fully local mode (`pointe local`), none of these goes anywhere: no key is read, from the environment or the
Keychain, so no vendor can be reached, and the text-model server listens on loopback only. The daemon uses that
server only when the program listening on its port is the one `pointe local` started (its pid file) or its child:
otherwise another account that took the port would receive every transcript, so the start is refused. See
[docs/features/local.md](docs/features/local.md).

With "Voice stays on your Mac" (`pointe local voice`), no audio goes to a vendor: ears and mouth run on the Mac, the
Soniox and ElevenLabs keys are never read, meeting mode is off, and every path that would stream audio out (cloud ears or
mouth, a realtime front, the echo guard's mirror stream, meeting ears) is refused in code. The brain, reader and gate
vendors still receive text. See [docs/features/voice-stays-local.md](docs/features/voice-stays-local.md).

With `openai_url` set, the OpenAI text models are served by a host you choose (Azure OpenAI, for example): that host
receives what the brain, reader and gate vendors would, over https only, and the OpenAI key is sent there and never to
OpenAI, so OpenAI's audio services are refused. See [docs/features/openai-url.md](docs/features/openai-url.md).

The vendors' own SDKs would follow variables set for Claude Code or another tool, such as `ANTHROPIC_BASE_URL`,
`ANTHROPIC_AUTH_TOKEN`, `OPENAI_BASE_URL` or `GOOGLE_GENAI_USE_VERTEXAI`, and send your keys and session content to
that host, or a gateway's header to the vendor. Pointe takes them out of its environment at start and names each
vendor's own address in its clients (`vendors.SDK_ROUTING_ENVS`, `tests/test_sdk_hosts.py`); only the Claude Code it
starts gets them back, so a copy of a session runs through your gateway as your session does.

Choose vendors you are allowed to send that content to. `pointe doctor` shows which ones are in use. Pointe has no server
and no telemetry, and the page loads nothing from outside your machine.

**No telemetry from its libraries either.** onnxruntime, which runs the voice detector, the voice lock and kokoro-onnx,
connects to Microsoft's telemetry collector (`*.events.data.microsoft.com`) when it loads, from native code (seen with
1.31.1). Pointe sets `ORT_DISABLE_TELEMETRY=1` before onnxruntime can load, in every setup: `pointe/no_telemetry.py` is imported
first by every module that can reach it, and `bin/voice-daemon`, `bin/pointe`, `bin/voice-doctor` and `bin/claude-voice`
export it for their child processes. `tests/test_no_telemetry.py` fails if any module reaches onnxruntime without it.
Measured: with it set, no connection to Microsoft in isolation or during an audio suite
([docs/features/voice-stays-local.md](docs/features/voice-stays-local.md#measured)).

## Supply chain

Pointe is installed from this repository and runs with your keys, so what reaches your machine matters as much as what
leaves it. The inventory, with each source's pin and its verification, is
[docs/security/supply-chain.md](docs/security/supply-chain.md).

- **How it is built.** There is no build and no package: `claude plugin install` clones `main`, and everything runs
  from that checkout with `uv run --locked`. Python packages come from PyPI at the exact versions and SHA-256s in
  `uv.lock`; uv refuses a mismatch. The Node channel (launch mode only) installs with `npm ci --ignore-scripts` from
  its lockfile. uv itself, when setup installs it, comes from the installer for one version, checked against a SHA-256
  before it runs (`bin/install-uv`). Models are fetched by SHA-256 (release files) or by commit (Hugging Face), pinned
  in `pointe/assets.py`, and refused on a mismatch. Nothing in `bin/`, `hooks/` or `plugin/` fetches code at run time; the page
  loads nothing from outside your machine; onnxruntime's telemetry is off.
- **How to verify.** In Claude Code's plugin folder: `git rev-parse HEAD` against the tag on GitHub, `uv lock --check`,
  and `uv run --locked pytest -q tests/test_supply_chain.py`, which checks the pins, the allowlists and the egress list
  against the tree. CI runs the same on every push, plus pip-audit over every locked version, and Dependabot opens
  grouped weekly bumps that a person reviews (`.github/`).
- **How to report.** A suspicious dependency, download or install step is a vulnerability: use GitHub's private
  vulnerability reporting on this repository or security@ballerine.com, as at the top of this page.
- **Known limits.** You get `main` at install time (release tags are not signed yet); `bin/voice-connector` pulls
  `twingate/connector:1`, a moving tag, by design; a model you name by hand (`pointe local --model`) is not pinned.

## Files

`~/.claude-voice` is 0700. It holds the token, the page key, session notes, `daemon.log`, and `journal.jsonl`, a full record of
each call with what you said and session content. Every line the daemon logs has the values of the keys it holds, the
page key and the token replaced with `[key]` before it reaches `daemon.log` or the journal (an exception's own text
under a traceback is not rewritten). With phone access it also holds the pairing secret, a TLS key and the
connector's tokens. With the voice lock it holds `voiceprint/` (0700; one file per enrolled device, 0600): biometric data,
computed and kept only on this Mac, deleted from Settings → Voice lock on the page or in the app. `models/` holds the
speaker model. With fully local mode, `local/` holds the text-model server's environment, its log (which may hold session
content in errors) and `config.before-local.json`, the choice `pointe local off` restores; the models themselves sit in
the Hugging Face cache (`~/.cache/huggingface`) and Kokoro's in `~/.cache/pipecat`. The journal records an ignored utterance's length and score, never its words. `briefings.json` (0600) keeps
the last seven briefings, written out per session and redacted. `night-shifts.json` (0600) keeps the last seven night
shifts: tasks, what sessions reported and any approval request they waited on, with credentials masked. `dictionary.json` (0600) holds the names you added or
fixed (Settings → Dictionary on the page or in the app shows, edits and deletes each one); it never takes a yes, no or
stop word, anything `readout.mask` would hide, or words from a meeting. Delete what you no longer need.

## Machines

Sessions on another Mac or a Linux host join the voice through a node there ([docs/multi-machine.md](docs/multi-machine.md)).
The Mac with the call (the hub) keeps every rule above for them.

- **Pairing.** The hub makes a one-time code: single use, 10 minutes, about 40 bits, kept only as a hash in memory, and
  accepted only while it is outstanding. Each address may try 5 codes at once, then about one a minute, checked before
  the code is compared, so one address cannot try enough to cancel the invite. After 20 wrong codes from all addresses
  together it is cancelled, and the page, the app and `pointe hub invite` say how many came and from which addresses.
  `/voice/node/pair` and `/voice/phone/pair` take no secret, so they answer 403 before reading a byte of the body
  when no code is out, and read at most 4 kB of it when one is (413 past that). No invite, an expired one and a wrong
  code get the same 403 text; only the owner is told why an invite ended. A caller can still tell that a code is live
  from a refused oversized body (413) or the rate limit (429), which answer only then; that gives no code.
  A guesser behind the same connector as your machine can delay it by a minute, not lock it out. Making it from the
  app needs Face ID there; the daemon makes one for any holder of the phone key (see Phone access).
  The node checks the hub certificate's SHA-256 against the fingerprint in the invite before it sends anything. It
  writes the hub's answer only if every field has the form the hub makes (the hub and node ids 16 hex digits, the key 64,
  plain names), so a hub cannot name a file outside `node_keys/`. The hub
  then shows the node's name, address and key fingerprint, so you can see that the machine that paired is yours.
- **The link.** The node dials the hub's TLS listener (the phone's) and proves its 256-bit key with an HMAC over a fresh
  challenge from the hub; the key itself never crosses. Before that proof, at most 8 sockets from one address and 32 in
  all may wait for it (10 seconds each), and the listener takes no WebSocket message over 1 MB. One connection per key: a copy of a node cannot connect while
  the node is connected. `pointe hub revoke <name>`, Settings → Machines on the page (two clicks) or in the app (a
  confirm, then Face ID) ends it; `pointe pair rotate` or `off` ends every machine's at once.
- **What crosses.** To the hub: each session's transcript and permission requests, with credentials masked on the node
  (`readout.mask`), names, folder paths and up to 40 file names; and, only when you look for sessions to add, each
  listed session's name, folder, agent, age, title, keywords and first and last request (160 characters each), never
  its transcript path, socket or account. To the node: your requests to its sessions and your
  answers to its prompts. A node holds no vendor key. Its sessions' content reaches the hub's vendors, as the hub's own
  sessions' does; `pointe node join` and `pointe node status` name them.
- **Approvals, checked twice.** The node re-checks voice and notification approvals against its own copy of the request:
  a spoken yes counts only if the hub read out exactly the text the node computed from the unmasked request, and a
  notification's Approve only for a request the node can read out. **A tap is trusted from the hub, as the hub's own
  page is trusted. What a tap approves on the hub's screens is the masked preview; the exact unmasked request is in the
  session's own terminal.** A node can refuse remote taps on requests it cannot read out: `"remote_taps":
  "readable_only"` in its `~/.claude-voice/config.json` (off by default).
- **Offline.** When a node's link drops, every prompt it held goes back to its own terminal, and a late answer is refused
  as stale. The screens show no Approve or Deny for a session that is offline.
- **Files.** On the hub, `nodes.json` (0600) holds each node's key; anyone who reads it can act as any node toward this
  hub. On a node, `node_keys/<hub id>` (0600). Mirrors of remote transcripts sit under `harness/remote/` (0700, files
  0600), and are deleted 7 days after their session left.

## Security reviews

From Pointe's public launch, its security is reviewed with Claude Mythos 5.2 through Claude Code on this schedule:

- **Every week:** the code that changed that week, and one of the five areas below in full, in rotation.
- **Before a tag:** a release that changes a boundary on this page (the listeners and their authentication, pairing,
  what a spoken word or a tap can approve, how keys reach processes, the install path) is not tagged until that change
  has been reviewed.
- **Every quarter:** all five areas in full.

Each pass reads one commit with read tools only. The areas are the network and pairing, approvals and voice, secrets and
supply chain, the page, and the apps. A maintainer checks every finding against the code. Each fix lands with a test
that failed before it, and the fixes are reviewed again before the release. Results, with each finding's status, are
published in [docs/security/reviews/](docs/security/reviews/README.md). `tools/security_review.sh` runs the same
review; `--since` limits it to the week's changes.

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
  command line when `bin/voice-open` runs (`open` on macOS, `xdg-open` and the browser on Linux), and any other user of
  the machine can read a command line with `ps`, on macOS as on Linux.
- **While the voice holds a prompt, the terminal also shows it**, and either can answer. It waits up to 280 seconds. If you answer in the terminal, the daemon may not notice at once, because of how it reads a closed connection (Low; a known limit).
- **Two pages with the key can both be in a call.** Keep it to one.
- **A read-back's yes can come a moment early.** A yes to the read-back of a start, a close, a night shift or a meeting's
  action items counts from when the line is queued, not from its first sound, so a stray "okay" in the half second
  before it plays can confirm it. A permission prompt's yes waits for the read-out's audio. (Low; to be closed.)
- **The voice lock scores more than the yes.** It scores the voiced audio since the last thing it scored, so your cough
  or hum just before a bystander's "yes" can count toward a match. It still fails closed when unsure. (Low, not
  measured; to be closed.)

## The Mac app

The Mac app (`apps/macos/`, [docs/mac-app.md](docs/mac-app.md)) is another client of the daemon on the same Mac. It changes
no rule above and adds no listener.

- **It is the page, to the daemon, and never sends the page's key.** It connects to `127.0.0.1` only. It reads
  `~/.claude-voice/page_key` and `~/.claude-voice/token` (both 0600) into memory at each connect, and puts on every
  request and on the call's socket a proof instead (`X-Pointe-Proof`, `pointe/local_proof.py`): an HMAC keyed by both, over
  the time, a random nonce, the method, the path, the query and the body's SHA-256. The daemon checks it before it
  reads the body and accepts it once, within 120 seconds, and only with the token of its own start, which
  `bin/voice-daemon` writes anew at every start. A proof opens what the page's cookie opens.
- **It checks who listens first.** Before it sends anything, the listener on the port must be the process the daemon's
  pid file names, or its child, as `bin/voice-daemon` checks. A request that cannot connect drops the verified address,
  and the check runs again before anything else is sent; a refused one has the check run again too. The daemon can still stop, and another program take the port, between
  two checks: that program gets proofs, not the key. Each is spent on a replay, good for its one request only, and
  refused by the next daemon start. `lsof` cannot see another user's listener, so the app takes that port as "not
  running" and does not connect.
- **Approve asks who is there.** A click on Approve in the window asks for Touch ID, an Apple Watch or the account
  password (the page on the Mac asks for nothing); Deny never asks. The daemon still takes the click only for the
  request that is pending. A notification's Approve follows the same daemon rule as the phone's.
- **No model key.** The app checks only whether a key is in the Keychain (attributes, never the secret). Adding one
  runs the plugin's own `pointe key` window.
- **The shortcut** is a Carbon hot key: macOS tells the app about that one combination. It has no Accessibility and no
  Input Monitoring permission and sees no other key. While a press is open it reads that one key's up or down state.
- **One entitlement**, the microphone, under the hardened runtime. Not sandboxed: it starts the plugin's
  `voice-daemon ensure` and reads the state folder. It makes no outbound connection and looks for no updates.
- **The plugin's scripts get none of the app's permissions.** Any process of yours can edit the plugin's folder, and
  macOS counts a child as the app that started it, microphone permission included. So the app starts every script
  (`voice-daemon`, `pointe key`, `pointe setup`, `voice-open`) disclaimed (`CommandRunner.swift`): with
  `posix_spawn` and macOS's `responsibility_spawnattrs_setdisclaim`, a libSystem call that is not in Apple's headers,
  so macOS judges the script by its own permissions, not the app's. If the call is missing or refused, the app starts
  nothing and says it can't start its scripts safely on this macOS. The daemon needs no microphone: call audio reaches it over the socket. An app
  for the App Store could not use that call; this one is built from source.
- **Known limits:** code running as you can read the page key the app reads. The browser page still sends the page key
  as its cookie, so a program that holds the port while the daemon is down gets the key from an open page's next
  request.

## Phone access (experimental, off by default)

`bin/voice-remote` adds an HTTPS listener for a phone on a private network. Remote requests need the configured name and a
pairing cookie. The listener is decided by the port that accepted the connection, never by `Host` or forwarded headers.
A request from a web page, HTTP or WebSocket, must carry exactly this listener's origin, `https://<name>:7443`: scheme,
name and port. Cookies ignore ports, so a page on another port of the same name (a dev server, `tailscale serve`) would
otherwise get the pairing cookie and open a call.
Limits: the pairing link is a lasting secret, despite the word "link", so treat it as a password; `pointe pair rotate`,
or Unpair all in Settings → Phone, replaces it. The page it opens keeps a key derived from it in its address (`/voice?k=…`), because "Add to Home Screen"
saves the address and a Home Screen app does not share Safari's cookies: that key reaches the browser's history, synced
tabs and screenshots, and opens the page to anyone who can also reach the listener, until `pointe pair rotate` or Unpair all. `pointe pair off` (and `bin/voice-remote off`) leaves the connector and its tokens in place. And `bin/voice-connector` pulls
`twingate/connector:1`, a moving tag. Call audio over this path is one TCP connection.

### The iPhone app

- **Pairing.** `pointe pair tailscale|wifi|host <name>` makes a TLS certificate for that one name, and a QR code with its
  SHA-256 and the phone's own key (`phone_key`, 0600). The app keeps both in the Keychain and talks only to that Mac.
- **Only a code scanned or pasted in the app pairs** (`PairingFlow.swift`). The app first shows the Mac's address and
  the first 16 characters of its certificate's SHA-256, and pairs only on the owner's confirm; the page's Settings →
  Phone and the Mac app's show the same 16 beside the code to compare. The confirm pairs only the code it shows: one the
  camera reads under it is ignored. Replacing a pairing names both Macs and needs Face ID or the passcode, and the old
  pairing stays until the new Mac has answered: the code redeemed, or, for a `pointe pair` code, the new key answered
  over the pinned connection. Unpair this phone asks first and needs Face ID or the passcode too, so unpairing and then
  pairing anew (a first pairing asks for neither) does not get around it. A `pointe://` link that
  opens the app from outside (the Camera, another app, a web page) pairs nothing, whatever it holds: any app or page can
  open one, and another app can register the same scheme. It only opens a sheet that says to scan the code inside
  Pointe. The app still registers the scheme for that sheet; without it, an app that claims `pointe://` would be the
  only one iOS could hand a Camera-scanned code to. The UI tests' launch settings that pair or forget a pairing
  (`POINTE_PAIR`, `POINTE_FORGET`) are compiled into Debug builds only.
- **A code scanned outside the app can still reach another app.** If a person scans the page's code with the Camera and
  another installed app has claimed `pointe://`, iOS may hand that app the link. With the page's code, that app can
  trade the one-time code for a phone key of its own within the 5 minutes; the page then shows "Connected:" with the
  name it chose, and Unpair removes it. With the terminal's code (`pointe pair show`) it gets the lasting key. The page
  and the app say to scan inside Pointe, and `pointe pair show` says not to use the Camera. The Mac does not ask for a
  confirm before a new phone's key works (a known limit).
- **Pairing from the page** (Settings → Phone, `pointe/phone_pairing.py`). The page lists the routes this Mac has (Tailscale, a
  name you set up, the Wi-Fi) and shows a QR code made on the Mac, with no outside service. The QR holds the listener's
  name, its certificate's SHA-256 and a one-time code, not the phone key: single use, 5 minutes, about 40 bits, kept only
  as a hash in memory, with the same bounds on wrong codes as a machine invite (5 at once per address, then a slow refill,
  checked before the code; the invite cancelled after 20 from all addresses together). The app checks the certificate first and only then sends the code to `/voice/phone/pair`,
  which answers the phone key. That route takes no other secret and refuses a request with an `Origin` (a web page).
  The routes that make a code, list routes and unpair answer only the page on this Mac, by its cookie: the phone key,
  the daemon token and a page opened over the TLS listener get 403. The status shows paired phones by name and time
  only; neither the status nor the log carries a code, a link or a key. Choosing another route makes a new certificate
  (the page says so first): every phone and machine paired before must pair again.
- **A copied code** (the Mac app's "Can't scan? Copy the link", a machine's invite line in either app) is marked
  concealed on the Mac (`org.nspasteboard.ConcealedType`, which clipboard managers skip) and cleared when the code ends
  if nothing else was copied since; on the iPhone it stays on that phone (no Universal Clipboard) and expires with the
  code. The page's own Copy button is the browser's and gets neither.
- **A key for each phone.** Each pairing from the page mints that phone its own 256-bit key, returned once;
  `phones.json` (0600) keeps only its SHA-256, with the phone's name and when it paired and was last seen. Every route
  that takes the phone key takes any paired phone's key; each check compares against every stored key in constant time,
  with no early exit. Unpair (two clicks) signs out that phone alone, from its next request, and ends its call if it has
  one up; another phone stays connected. Unpair all signs out every phone. Pairing the same phone again retires its old key.
- **A call that outlives a dropped link** (`pointe/calllink.py`, `pointe/phone.py` protocol 5). The daemon answers a call's hello
  with a token for that call (144 bits from `secrets`). A new socket takes the call over only with that token, on the
  same route (the phone's or the page's) and, for a phone, with the same phone's key, while the call is up or held: 30 s
  after its link dropped without a hang-up. The socket it replaces is closed. The token travels only inside the call's
  own socket (TLS on the phone listener), is compared in constant time, is never logged or put in the status, and ends
  with the call. It gives no access the paired phone did not already have: Unpair and `pointe pair rotate` still end
  the call at once, and a hang-up (close 1000) ends it with no hold. A typed line carries an id of the app's so a resend
  is taken once; the daemon keeps the last 64 ids in memory only.
- **The shared key from before.** `phone_key` (0600), which `pointe pair` put in its QR code before per-phone keys,
  still works, as one phone named "Paired phone" until the app reports its name (an `X-Pointe-Device` header). So the
  upgrade signs no one out. `pointe pair show` still prints that old link with that key, and mints it again if it was
  unpaired: it works with the daemon stopped, which the page's one-time code cannot. It says to scan it inside the app
  and not with the Camera, and Unpair on the page revokes it like any other phone.
- **Pinning, and App Transport Security off.** The app accepts exactly the certificate it paired with, and nothing else,
  CA-signed or not. iOS's App Transport Security can't be scoped to a name you pick (a Twingate or VPN name), and it
  refuses a self-signed certificate before the app's own check runs, so it is off for this app. The pin is the stronger
  check: ATS trusts any CA-issued certificate for the name, and the pin trusts one certificate.
- **What the phone key opens**, and nothing else (`guards._PHONE_PATHS`):
  - the call (`/voice/phone`), status (`/voice/status`: the sessions, each pending request with its id, the last turns
    of the conversation, the words being heard) and approve (`/voice/approve`);
  - driving the sessions: `/voice/switch`, `/voice/disconnect`, `/voice/hung-up`, `/voice/rename`, `/voice/mode`,
    typed words (`/voice/say`, `/voice/correct`, `/voice/polish`), a new session in a folder the Mac allows
    (`/voice/new-session`), adding sessions listed on the Mac (`/voice/add-sessions`), the night shift
    (`/voice/night-shift`), the brain dump (`/voice/dump`, `/voice/listen`), the challenge (`/voice/challenge`), drive mode (`/voice/drive`), mute (`/voice/reading`, and `/voice/read` to mark Pointe's lines
    read), skip (`/voice/skip`: it stops the line being said and answers nothing; a request whose read-out was
    skipped is read out again before a yes counts), the held news of session mode (`/voice/held`: told aloud, never approves), alerts (`/voice/attention`) and the conflict alarm
    (`/voice/conflicts`: dismiss, or ask one side: the card's question, sent to that session as a conflict check,
    never as the user's words, and it approves nothing);
  - meetings and notes: `/voice/meeting`, `/voice/meeting/transcript`, `/voice/notes`;
  - settings: `/voice/prefs` (every setting except the voice lock, which has its own route, and the folders new
    sessions may start in, which only the Mac changes), the voice lock (`/voice/voiceprint`: enrol, delete, level), the
    dictionary (`/voice/dictionary`), and briefings (`/voice/briefings`, `/voice/briefings/latest`,
    `/voice/briefings/schedule`);
  - Show while it says (`/voice/artifact`), once `show.on_phone` is on;
  - machines: `/voice/hub/invite`, `/voice/hub/nodes`, `/voice/hub/revoke`, and `/voice/machines/add` (adds a machine
    somebody invited this person to, from its owner's one-time line: the daemon then connects out to that machine,
    and only to the certificate the line names).

  Not the model's whole context, the page's own routes (phone pairing, keys, setup), or anything a Claude Code session
  uses.
- **Face ID is a check in the app, not in the daemon.** The app asks for Face ID or the passcode before it approves,
  turns on Show while it says or Approve from notifications, lowers or deletes the voice lock, adds a voiceprint beside
  a stored one, or makes a machine invite. The daemon cannot see Face ID and takes the same request from anything that holds the key. So a leaked phone
  key can do all of the above without it (a voiceprint beside a stored one only within a minute of the owner's voice
  matching on the call, which the daemon checks): approve any pending request (status carries its id), turn on
  `show.on_phone` and read what the voice showed, turn on `alerts.watch_approve`, and pair a machine of its own, which
  stays paired after the phone is unpaired. If a phone key may have leaked, Unpair it, run `pointe pair rotate` (it
  signs out every machine too), and check Settings → Machines.
- **Show while it says reads source files.** The page on this Mac always shows the files and test output the voice talks
  about. The phone key, and a page opened over the TLS listener, get nothing (no `showing` in status, 403 from
  `/voice/artifact`) until `show.on_phone` is on (Settings → Show while it says; the app asks for Face ID to turn it
  on, but the daemon takes the setting from any holder of the phone key). Once on, a leaked phone key can read what the
  voice showed: the last ten reports' files, inside each session's
  folder only. Either way the daemon never takes a path from the caller, shows only tools that ran (never a tool still
  waiting for approval), refuses files outside the session's folder after resolving symlinks, hidden files and
  secret-looking names (`.env*`, `*.pem`, `*secret*`, `*key*`, `id_*`, `*credential*`, ...), binary files and files over
  512 kB, and masks secret-looking values (known token shapes, private keys, `name = "..."` and unquoted `name: value` for secret-like names, URL
  passwords, and the values of this machine's own key variables) in file lines, diffs, test output and commands.
  Diffs read `HEAD` with `git cat-file`, never `git diff`, so a repository's filters and diff drivers do not run.
- **Approve needs Face ID** or the passcode in the app; deny never does. One opt-in exception: with "Approve from notifications"
  on (`alerts.watch_approve`, off by default; the app asks for Face ID to turn it on), a notification's Approve needs an
  unlocked iPhone or a watch on the wrist instead. The daemon accepts it (`via: "notification"`) only for a request it can
  read out, bound to that request's id (`pointe/alerts.py`).
- **What Face ID protects, and what it does not.** Every Face ID or passcode check in the app (Approve; starting,
  adding or joining sessions; night shift; a machine invite or revoke; lowering the voice lock, deleting a voiceprint
  or adding one beside a stored one; turning on show while it says or approve from notifications; replacing the pairing) runs in the app,
  before it sends an ordinary request with the phone key. It stops a person who holds your unlocked iPhone. It does not
  bind the key: the daemon cannot tell whether Face ID ran. Whoever has the phone key itself (a `pointe pair` code that
  was copied or photographed, an app that redeemed a code scanned outside Pointe, the Keychain of a jailbroken phone)
  can do everything the key opens (`_PHONE_PATHS` in `pointe/guards.py`), approvals included, with no Face ID. Unpair on the
  Mac (Settings → Phone) ends that key at its next request.
- **Notifications** (phone, watch, desktop) show only the read-out form of a request, never its full text or the model's
  description; a request that cannot be read out shows only its tool. Credential-like values follow the same rule as
  the voice (`readout.redact`): never shown, never said.
- **The widget and the Live Activity** (Talk to Pointe, `docs/features/push-to-talk.md`) show the Mac's name, whether it
  answered, how many sessions need you, and the call's state line: never a session's name, a request's text or a word
  said. The widget's copy is in the app group the app shares with its widget extension, written by the app (none on a
  free Personal Team: the widget is then a plain button); the extension holds no key and reaches no Mac. Both show on the
  Lock Screen if placed there.
- **Deleting the app does not unpair.** The pairing is in the iPhone's Keychain, which outlives the app, and the Mac
  still takes its key: a reinstall is paired again without a scan. Unpair on the Mac to end it.
- **Revoke:** Unpair in Settings → Phone. The phone paired from the terminal can also be revoked by deleting
  `~/.claude-voice/phone_key`; it takes effect at the next request. Pairing again with the same name keeps the
  certificate, so a browser that trusts it keeps working.
- **Revoke everything at once** (a lost phone, a QR code, link or invite someone else saw): `pointe pair rotate` makes a
  new certificate and a new browser pairing secret, and signs out every phone (`phones.json`, `phone_key`), every
  browser and every machine (`nodes.json` keeps only the hub's id). `pointe pair off` signs out the same and stops
  listening. A running daemon refuses the old keys at their next request, because it reads these files at each check;
  within about five seconds it restarts the listener on what is on disk and closes the calls and links that were up.
- Tested on a real iPhone over Twingate, and in the simulator against a real host name.
