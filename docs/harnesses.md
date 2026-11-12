# Harnesses: Claude Code, OpenCode, Codex, and how to add another

Pointe's voice side (ears, brain, mouth, approvals, routing) does not care which coding agent runs a session. It needs
five things from the agent, and each harness adapter in `harnesses/` provides them:

| Capability | What Pointe needs | Adapter |
|---|---|---|
| Join | a session id, a name, a folder, and a way to tell it is still running | `join(argv)` (for `pointe join <harness>`), `alive(session)`, `probe(session)` |
| Watch | its activity and final messages, to report and keep notes | `watch(session, feed)`, `transcript_path`, `noise`, `title` |
| Send | type the user's request into the running session | `send(session, text)` |
| Approvals | see a permission request, put it to the user, answer it | calls `HOST.hold_permission(session, tool, input, gone, deadline)` |
| Side questions | answer "by the way" from a copy, never touching the live session | `side_question(session, question)` |

Each adapter also declares what it can do, and `/voice/status` shows it per session (`capabilities`), so the brain and
the screens never promise a missing feature: `approvals`, `side_questions`, `attach` (joins a session the user already
runs), `spawn` (drives only sessions Pointe starts). Plus `label` (how the feed names it: `claude-code`, `opencode`, `codex`),
`agent` (what the voice calls it: "Claude", "OpenCode"), `joins_mid_turn`, and `permission_deadline`.

Everything else (the brain, consent rules, the read-out allowlist, Face ID taps, reports, notes, routing, the apps)
is shared. The feed lines an adapter produces are the bracketed lines `sessions.follow_transcript` writes, labelled
with the harness; a turn end is `harnesses.finished_tag(label)`, read back by the daemon through one constant.

## One call, several harnesses and accounts

Sessions of different harnesses, and Claude Code sessions of different accounts, sit side by side: routing, status,
reports and approvals work per session. In practice:

- **Names:** the same folder in two harnesses registers as "shop" and "shop opencode". "The opencode one" picks a
  session by its harness (Claude Code is never matched by "Claude": every "ask Claude Code to …" would).
- **Approvals:** each session holds its own prompt; one answer never answers another session's (tested with a Claude
  Code and an OpenCode prompt at once).
- **The voice names each agent:** reports and notes about an OpenCode session call it OpenCode, not Claude
  (`brief.for_agent`).
- **Several Claude accounts:** a session registers its config dir (`CLAUDE_CONFIG_DIR`), so its transcripts, title and
  "by the way" copy come from that account's folder. The daemon itself does not inherit the starting session's account.

## Claude Code (`harnesses/claude_code.py`)

| Capability | How |
|---|---|
| Join | `/pointe:voice` in the session registers it: its id, folder, process id, transcript path, config dir, inbox socket. `/pointe:leave` takes it off. |
| Watch | the transcript under the session's config dir (`projects/`), followed live; a `/clear` or `/resume` re-points it (`transcript_path`) |
| Send | the session's inbox socket (Claude Code 2.1.224+), or its voice channel in launch mode |
| Approvals | the plugin's `PermissionRequest` hook posts to `/voice/permission-hook`, which goes through the same `hold_permission` as any harness (280 s, under the hook's own timeout) |
| Side questions | `claude -p --resume <id> --fork-session`, locked down, in the session's own account |

## OpenCode v2 (`harnesses/opencode.py`)

OpenCode's TUI is a client of a local background service (unless started with `--standalone`), so the voice drives
the same session the user is typing in.

| Capability | How |
|---|---|
| Join | `pointe join opencode` in the session's folder picks its running (or latest) session; `--session ses_…` picks one; `pointe leave opencode` takes it off. `pointe join opencode --install-command` adds `/voice` to OpenCode (restart OpenCode after installing; not yet loaded in a real OpenCode). |
| Watch | one SSE connection to `/api/event`; an event naming the session triggers a re-read of `/api/session/{id}/message` (the stream has no replay), plus a 5-second poll. New, finished messages go to a mirror transcript under `~/.claude-voice/harness/opencode/`. With no call up, the daemon's liveness loop probes `/api/session/{id}`: a deleted session drops off, and its OpenCode title is followed. |
| Send | `POST /api/session/{id}/prompt` with `delivery: "steer"` |
| Approvals | `permission.asked` (or a pending request listed by `/api/session/{id}/permission`) goes through `hold_permission`; the answer is `POST …/permission/{id}/reply` with `once` or `reject`. If the user answers in OpenCode first, the voice lets go. |
| Side questions | `POST /api/session/{id}/fork`, a prompt to the fork, its answer, then the fork is deleted |
| Auth | the service URL from `opencode service status` (random localhost port) and HTTP Basic (`opencode` and the password in `~/.config/opencode/service.json`), read when needed and never logged |

Verified against OpenCode v2.0.27's OpenAPI spec and live, read-only (sessions, mirror, event stream). An end-to-end
call with a real OpenCode model (a prompt, a spoken report, a voice approval) has not been run yet.

## Codex CLI (`harnesses/codex.py`)

Codex 0.160+ runs a shared app-server daemon. A TUI started with `codex --remote unix:// -C "$PWD"` is a client of
it, so the voice drives the thread the user is typing in. A plain `codex` runs its app-server inside its own process
and holds the thread's writer lock: it cannot be joined, and Pointe says how to start it instead (alias `codex` to the
command above). Protocol: JSON-RPC over a WebSocket on the Unix socket `~/.codex/app-server-control/app-server-control.sock`.

| Capability | How |
|---|---|
| Join | `pointe join codex` in the folder picks the newest thread there that the daemon has loaded (`thread/list {cwd}` and `thread/loaded/list`); `--thread <id>` picks one; `pointe leave codex` takes it off. Then `thread/resume {excludeTurns}` subscribes. It fails with "no rollout found" before the thread's first turn (retried) and "active writer" for a plain TUI (told to the user). |
| Watch | `turn/started`, `turn/completed`, `thread/closed`, `thread/name/updated` for the thread; on each turn end, `thread/turns/list {itemsView: full}` is read, and finished turns go to a mirror transcript under `~/.claude-voice/harness/codex/` (user message, commands as `Bash` tool uses, the final answer as the end of the turn). |
| Send | `turn/start` when idle; `turn/steer {expectedTurnId}` during a turn (a steer to a turn that just ended falls back to `turn/start`) |
| Approvals | the server's `item/commandExecution/requestApproval` and `item/fileChange/requestApproval` go through `hold_permission`, with the command unwrapped from Codex's `/bin/zsh -lc '…'` so the read-out applies. The answer is a decision Codex offered: `accept`; `decline` if offered, else `cancel`. `serverRequest/resolved` means the TUI answered first, and the voice lets go. Permission-grant requests (`item/permissions/requestApproval`) stay with the TUI. |
| Side questions | `thread/fork {ephemeral, sandbox: read-only, approvalPolicy: never}`, a turn on the fork, its final answer; nothing is kept |
| Liveness | `thread/closed`, or status `notLoaded` (the TUI closed it); the daemon unreachable for a minute. With no call up, the liveness loop reads `thread/read`. |

The daemon updates itself and restarts when idle: the link reconnects and resumes every joined thread, and turns that
finished meanwhile are read from `thread/turns/list`. Resuming a thread from Pointe marks it as touched by another
client in Codex's own records (its `source` and `originator`). Each Codex turn costs Codex about 95k input tokens.

## Adding a harness

1. Subclass `Harness` in `harnesses/<name>.py`; set `name`, `label`, `agent` and the capability flags truthfully.
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
7. Register it in `harnesses/__init__._load`, and add a fake-service test like `tests/test_opencode.py` plus a case
   in `tests/test_mixed_harnesses.py`.

## Next: Pi

**Pi.** Pi has no server: a small extension inside Pi opens a 0600 unix socket and streams its events; the Python
adapter mirrors them. Pi has no built-in approvals, and the adapter declares `approvals = False` rather than gating
every tool call through the voice.

**Spawn-only agents (Gemini CLI, Cursor CLI)** need a `start(cwd)` capability the interface does not have yet, and do
not fit "it keeps running in its terminal; join it again there". Deferred.
