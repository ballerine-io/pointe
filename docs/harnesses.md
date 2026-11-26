# Harnesses: Claude Code, OpenCode, Codex, and how to add another

Pointe's voice side (ears, brain, mouth, approvals, routing) does not care which coding agent runs a session. It needs
five things from the agent, and each harness adapter in `pointe/harnesses/` provides them:

| Capability | What Pointe needs | Adapter |
|---|---|---|
| Join | a session id, a name, a folder, and a way to tell it is still running | `join(argv)` (for `pointe join <harness>`), `alive(session)`, `probe(session)` |
| Watch | its activity and final messages, to report and keep notes | `watch(session, feed)`, `transcript_path`, `noise`, `title` |
| Send | type the user's request into the running session | `send(session, text)` |
| Approvals | see a permission request, put it to the user, answer it | calls `HOST.hold_permission(session, tool, input, gone, deadline)` |
| Side questions | answer "by the way" from a copy, never touching the live session | `side_question(session, question)` |
| Stop | end the running turn when the user says "stop", "cancel that" or "hold on" | `interrupts`, `interrupt(session)` |

To be added from outside ("connect to the session about the pentest", [features/add-sessions.md](features/add-sessions.md)),
an adapter also lists what its harness runs and ran (`discover(since, cap)`, returning `discovery.Found` records), builds
the register body a session would send itself (`attach_body(found)`), and brings a closed one back (`reopen(found,
start_id)`; by default the same as joining). Design: [design/attach-by-voice.md](design/attach-by-voice.md).

Each adapter also declares what it can do, and `/voice/status` shows it per session (`capabilities`), so the brain and
the screens never promise a missing feature: `approvals`, `side_questions`, `attach` (joins a session the user already
runs), `spawn` (drives only sessions Pointe starts), `interrupt` (`now`: the harness cuts the turn, a running command
included; `next_step`: the turn ends after the tool call that runs; null: no supported way, and the voice says so). An adapter with `starts` can also start a new session in a
folder (`start(cwd, name, start_id)`, below, and [features/new-session.md](features/new-session.md)). Plus `label` (how the feed names it: `claude-code`, `opencode`, `codex`),
`agent` (what the voice calls it: "Claude", "OpenCode"), `joins_mid_turn`, and `permission_deadline`.

Everything else (the brain, consent rules, the read-out allowlist, Face ID taps, reports, notes, routing, the apps)
is shared. The feed lines an adapter produces are the bracketed lines `sessions.follow_transcript` writes, labelled
with the harness; a turn end is `harnesses.finished_tag(label)`, read back by the daemon through one constant.

## One call, several harnesses and accounts

Sessions of different harnesses, and Claude Code sessions of different accounts, sit side by side: routing, status,
reports and approvals work per session. In practice:

- **Names:** the same folder in two harnesses registers as "shop" and "shop opencode". "The opencode one" picks a
  session by its harness (Claude Code is never matched by "Claude": every "ask Claude Code to …" would). An unnamed
  "ask Claude Code to …" still never goes to another harness's session the conversation was with: with one Claude
  Code session, it goes there.
- **Approvals:** each session holds its own prompt; one answer never answers another session's (tested with a Claude
  Code and an OpenCode prompt at once).
- **The voice names each agent:** reports and notes about an OpenCode session call it OpenCode, not Claude
  (`brief.for_agent`).
- **Several Claude accounts:** a session registers its config dir (`CLAUDE_CONFIG_DIR`), so its transcripts, title and
  "by the way" copy come from that account's folder. The daemon itself does not inherit the starting session's account.

## Sessions on other machines

An adapter always runs on the session's own machine. A session on another Mac or a Linux host joins through the Pointe
node there ([multi-machine.md](multi-machine.md)): the node runs the same adapter (join, watch, send, approvals), and the
hub sees the session through one wrapper, `pointe/harnesses/remote.py`, that reads a mirror of its transcript and passes sends
and verdicts over the link. Badges, feed labels and `capabilities` still come from the real adapter, with one change:
`side_questions` is false, because a forked copy would have to run on the node. "By the way" questions about a remote
session are answered by the transcript reader, as for a harness that cannot fork.

## Claude Code (`pointe/harnesses/claude_code.py`)

| Capability | How |
|---|---|
| Join | `/pointe:voice` in the session registers it: its id, folder, process id, transcript path, config dir, inbox socket. `/pointe:leave` takes it off. |
| Watch | the transcript under the session's config dir (`projects/`), followed live; a `/clear` or `/resume` re-points it (`transcript_path`) |
| Send | the session's inbox socket (Claude Code 2.1.224+), or its voice channel in launch mode; with a reply address where Claude Code could hold or refuse it (below) |
| Approvals | the plugin's `PermissionRequest` hook posts to `/voice/permission-hook`, which goes through the same `hold_permission` as any harness (280 s, under the hook's own timeout) |
| Side questions | `claude -p --resume <id> --fork-session`, locked down, in the session's own account; a session signed in by an `ANTHROPIC_API_KEY` gets its copy started again on Pointe's Anthropic key (SECURITY.md, Keys) |
| Start | a new terminal window (`open -a Terminal` on a `.command` script; iTerm when it is running) with `claude --permission-mode default --name <name> --settings <file>`; the settings file's `SessionStart` hook runs `bin/register-session --start <id>`, so it joins in attach mode. Mac only. |
| Discover | open: `claude agents --json` for each account Pointe knows (`pid`, `cwd`, `kind`, `sessionId`, `name`, `status`), with the inbox socket from Claude Code's own record of the process (`sessions/<pid>.json`, `messagingSocketPath`: not a documented interface, checked against the roster and the socket's owner); recent: transcripts under `projects/` from the last 7 days, head and tail only |
| Attach | the same body `/pointe:voice` registers (id, folder, pid, transcript, config dir, inbox socket), from outside. Approvals reach the voice only where the plugin's hook runs in that session (enabled in its settings when it started, or `--plugin-dir`): otherwise the read-back says they stay in its terminal |
| Reopen | Start's terminal window with `claude --resume <id> --permission-mode default`, its `SessionStart` hook on matcher `resume`, in the session's folder and account. Mac only. |
| Stop | No supported way exists for another process to interrupt a running turn: an inbox message is read between tool calls, Escape is a key in its terminal, and `claude stop` stops a background session whole. The plugin's `PreToolUse` and `PostToolUse` hook, `bin/voice-stop-hook`, returns `"continue": false`, which the hooks reference documents as ending the turn after the hook runs. The daemon leaves a file named by the session id in `<state>/stop/`; the hook takes it, so the turn ends at its next tool step. A command that already runs finishes first. Without a stop waiting the hook reads nothing and prints nothing. Like approvals, it works only where the plugin's hooks run in that session. |
| A prompt in its terminal | `claude agents --json` (Claude Code's supported way to read session state), read when a session's tool call has gone quiet: `status: waiting` with its `waitingFor` (`permission prompt`, `input needed`, `sandbox request`, `dialog open`) |

A prompt the voice does not hold (no call was up, the hold ran out, approvals are left to the terminal, a question, a
dialog) can only be answered in the terminal. The transcript cannot tell it from a tool that runs, so the session used
to count as working. Now `/voice/status` gives it `working: false`, `needs` ("A permission prompt in its terminal.") and
`blocked_on`; the voice is told it stopped there and that a yes does not reach it. The words are fixed ones, never the
string Claude Code sent. At most one read per account every 15 seconds, and none while every session is idle or its
record is moving. With no call up the hub follows no transcript, so the adapter reads the end of it when the file
changes to tell whether a turn is open. A node reads it for its own sessions and ships it in its `sessions`
snapshot (since a pre-release build), so a session on another machine shows the same way.

A send can be held. Claude Code holds an inbox message to a session that bypasses permission prompts (plan mode can
count) for approval in its terminal, unless that session sets `crossSessionInbound` to `accept`; `hold` holds every
message and `refuse` drops it. Nothing comes back on the inbox connection. Claude Code reports a held, refused or
dropped message in a `peer_message_status` line to the reply address in the message's `from`, within a fraction of a
second, and the user's answer in the terminal later (`delivered`, `denied`, `expired`); an accepted message gets no
answer. A session given a reply address also tries to answer through it, which costs tool calls and adds words to its
reply, so `may_hold` offers one only where Claude Code could hold or refuse the message: a `crossSessionInbound` of
`hold` or `refuse` in the settings Pointe can read (managed, the account's, the repository's), or none and a bypassing
permission mode in the transcript. A `--settings` flag cannot be seen from outside. The address is a socket beside the
session's own (Claude Code answers no other) that lives for one message, or until a held one is answered (at most 10
minutes). A held or refused send is not delivered: the voice says so and names the setting, and `/voice/status` gives
the session `needs` with the same words; a held one is also a wait in its terminal, so it alerts like one.

## OpenCode v2 (`pointe/harnesses/opencode.py`)

OpenCode's TUI is a client of a local background service (unless started with `--standalone`), so the voice drives
the same session the user is typing in.

| Capability | How |
|---|---|
| Join | `pointe join opencode` in the session's folder picks its running (or latest) session; `--session ses_…` picks one; `pointe leave opencode` takes it off. `pointe join opencode --install-command` adds `/voice` to OpenCode (restart OpenCode after installing; not yet loaded in a real OpenCode). |
| Watch | one SSE connection to `/api/event`; an event naming the session triggers a re-read of `/api/session/{id}/message` (the stream has no replay), plus a 5-second poll. New, finished messages go to a mirror transcript under `~/.claude-voice/harness/opencode/`. With no call up, the daemon's liveness loop probes `/api/session/{id}`: a deleted session drops off, and its OpenCode title is followed. |
| Send | `POST /api/session/{id}/prompt` with `delivery: "steer"` |
| Stop | `POST /api/session/{id}/interrupt` (the service's `session.interrupt`, v2.3): it cuts the running execution, a running command included, and says whether one ran |
| Approvals | `permission.asked` (or a pending request listed by `/api/session/{id}/permission`) goes through `hold_permission`; the answer is `POST …/permission/{id}/reply` with `once` or `reject`. If the user answers in OpenCode first, the voice lets go. |
| Side questions | `POST /api/session/{id}/fork`, a prompt to the fork, its answer, then the fork is deleted |
| Start | `POST /api/session {location: {directory}, title}`; no agent, model or permission rules are sent |
| Discover | `GET /api/session?limit=` and `GET /api/session/active`: active sessions and ones touched in the last 2 hours are open, older ones recent; both join the same way (the service keeps them all) |
| Auth | the service URL from `opencode service status` (random localhost port) and HTTP Basic (`opencode` and the password in `~/.config/opencode/service.json`), read when needed and never logged |

Verified against OpenCode v2.0.27's OpenAPI spec and live, read-only (sessions, mirror, event stream). An end-to-end
call with a real OpenCode model (a prompt, a spoken report, a voice approval) has not been run yet.

## Codex CLI (`pointe/harnesses/codex.py`)

Codex 0.160+ runs a shared app-server daemon. A TUI started with `codex --remote unix:// -C "$PWD"` is a client of
it, so the voice drives the thread the user is typing in. A plain `codex` runs its app-server inside its own process
and holds the thread's writer lock: it cannot be joined, and Pointe says how to start it instead (alias `codex` to the
command above; `pointe setup codex` starts the app-server and offers the alias, [install.md](install.md#codex)). Protocol: JSON-RPC over a WebSocket on the Unix socket `~/.codex/app-server-control/app-server-control.sock`.

| Capability | How |
|---|---|
| Join | `pointe join codex` in the folder picks the newest thread there that the daemon has loaded (`thread/list {cwd}` and `thread/loaded/list`); `--thread <id>` picks one; `pointe leave codex` takes it off. Then `thread/resume {excludeTurns}` subscribes. It fails with "no rollout found" before the thread's first turn (retried) and "active writer" for a plain TUI (told to the user). |
| Watch | `turn/started`, `turn/completed`, `thread/closed`, `thread/name/updated` for the thread; on each turn end, `thread/turns/list {itemsView: full}` is read, and finished turns go to a mirror transcript under `~/.claude-voice/harness/codex/` (user message, commands as `Bash` tool uses, file changes as `Edit` with their paths, the final answer as the end of the turn). |
| Send | `turn/start` when idle; `turn/steer {expectedTurnId}` during a turn (a steer to a turn that just ended falls back to `turn/start`) |
| Stop | `turn/interrupt {threadId, turnId}` on the running turn (app-server protocol v2, checked against `codex app-server generate-json-schema` of 0.160) |
| Approvals | the server's `item/commandExecution/requestApproval` and `item/fileChange/requestApproval` go through `hold_permission`, with the command unwrapped from Codex's `/bin/zsh -lc '…'` so the read-out applies, and read from the folder Codex runs it in (`cwd`). A file change names no file: it is read word for word as what Codex sent (its grant root), and a yes or a tap answers it. The answer is a decision Codex offered: `accept`; `decline` if offered, else `cancel`. `serverRequest/resolved` means the TUI answered first, and the voice lets go. Permission-grant requests (`item/permissions/requestApproval`) stay with the TUI. |
| Side questions | `thread/fork {ephemeral, sandbox: read-only, approvalPolicy: never}`, a turn on the fork, its final answer; nothing is kept |
| Start | `thread/start {cwd}` and `thread/name/set`; no approval policy or sandbox is sent, and an answer with approvals `never` and sandbox `dangerFullAccess` is archived and refused |
| Discover | `thread/loaded/list` (open) and `thread/list {sortKey: updated_at}` (recent), sub-agent and ephemeral threads left out |
| Reopen | `thread/resume` on the shared daemon, then joined as an open thread; one that comes back with approvals `never` and sandbox `dangerFullAccess` is refused |
| Liveness | `thread/closed`, or status `notLoaded` (the TUI closed it); the daemon unreachable for a minute. With no call up, the liveness loop reads `thread/read`. |

The daemon updates itself and restarts when idle: the link reconnects and resumes every joined thread, and turns that
finished meanwhile are read from `thread/turns/list`. Resuming a thread from Pointe marks it as touched by another
client in Codex's own records (its `source` and `originator`). Each Codex turn costs Codex about 95k input tokens.

## Agents built on agent frameworks

OpenClaw, Hermes Agent and any A2A or OpenAI-compatible agent join as sessions of four more harnesses (`openclaw`,
`hermes`, `a2a`, `openai`, in `pointe/harnesses/`, sharing `agent.py`), behind `POINTE_AGENTS=on`. They are configured
with `pointe agent add`, not joined from a folder; their record is a mirror Pointe writes as turns finish in the
background. How-to: [agents.md](agents.md). Design: [design/agents.md](design/agents.md).

## Adding a harness

1. Subclass `Harness` in `pointe/harnesses/<name>.py`; set `name`, `label`, `agent` and the capability flags truthfully.
2. `join(argv)` returns the `/voice/register` body for `pointe join <name>` (id, name, cwd, and `transcript` if it
   has one; per-session data goes in `harness_data`, and `pid` may be 0).
3. `watch` produces the feed: either follow a transcript in the shape `sessions.follow_transcript` reads (what
   OpenCode does through its mirror), or call `feed(session, text, respond)` with the same bracketed lines, ending a
   turn with `finished_tag(label)`. The follower reads: `type` user/assistant, `message.content` (text or blocks with
   `tool_use`), `stop_reason == "end_turn"` for a final message, and skips `isSidechain`, `isMeta`. Override `noise`
   if the harness injects text into user turns. For Show while it says, give each `tool_use` an `id` and write its
   outcome as a `tool_result` block (`tool_use_id`, `content`, `is_error`) in a `user` entry, only once the tool ran:
   a shell command as `Bash` with `command` (test runs show their output), a file change as `Edit` with `file_path`
   (or `files: [...]`), a read as `Read`. A tool with no result is never shown.
4. `send`, `alive` (never blocking), and `probe` if liveness needs a network check.
5. Approvals: call `HOST.hold_permission(session, tool_name, tool_input, gone, deadline)` and send its answer back. If
   the harness has no approvals, leave `approvals = False`: do not make Pointe its permission policy.
6. `side_question` if it can fork; otherwise the transcript reader answers.
7. To let Pointe start its sessions: set `starts = True`; `can_start()` says why not in fixed words (not installed)
   or returns None; `start(cwd, name, start_id, skip=False)` starts one in the harness's default permission mode and
   returns its register body, or None when the session registers itself with `start_id`; pass every command line or
   request through `refuse_bypass`; raise `StartError` with words for the user. Leave `skips` False and refuse
   `skip=True`: only Claude Code starts a session that skips its prompts, by the user's setting. `open_hint(session)` says how to open it in a
   terminal. The daemon picks the folder and the name and does the read-back: an adapter never takes a path from
   anywhere else.
8. To be added from outside: `discover(since, cap)` with only the harness's supported interfaces and only this user's
   sessions, `attach_body(found)` (the body step 2 returns), and `reopen(found, start_id)` if a closed session needs
   more than joining (set `reopens_in_terminal` when it opens a window). Pass anything it starts through `refuse_bypass`.
9. Register it in `pointe/harnesses/__init__._load`, and add a fake-service test like `tests/test_opencode.py` plus a case
   in `tests/test_mixed_harnesses.py`.

## Next: Pi

**Pi.** Pi has no server: a small extension inside Pi opens a 0600 unix socket and streams its events; the Python
adapter mirrors them. Pi has no built-in approvals, and the adapter declares `approvals = False` rather than gating
every tool call through the voice.

**Spawn-only agents (Gemini CLI, Cursor CLI)** can use `start(cwd, name, start_id)`, and still do not fit
"it keeps running in its terminal; join it again there". Deferred.

## Cloud sessions hosted by the vendors

Claude Code on the web and Codex Cloud cannot be joined: neither vendor has a public read or approvals interface for them. What works, what doesn't, and why: [cloud-sessions.md](cloud-sessions.md).
