# Add sessions by voice: join the ones already open, reopen recent ones

Decided 2026-11-23, for 1.21.0. Until now a session reached the voice only from inside it (`/pointe:voice`,
`pointe join <harness>`) or because Pointe started it ([new-session.md](new-session.md)). This adds the third way: the
user describes sessions ("connect to the session about the recent pentest", "connect to all open Claude Code
sessions", "reopen yesterday's session about the billing migration"), Pointe finds them, reads back what it found,
and joins them on a yes. Nobody types anything in those sessions.

Joining a session gives the voice that session's transcript, its sends and (where the harness allows) its approvals.
So the rules come first, and each is in code with a test (`discovery.py`, `matching.py`, `guards.attach_request`,
`daemon.add_sessions`, `tests/test_attach_*.py`).

## The rules

1. **Nothing joins without a read-back and a yes.** By voice, the first sentence only finds and reads back. A session
   joins on the user's next plain yes within 60 seconds, or on a pick from a list the voice read ("the first one",
   "both"), bound to exactly the sessions in that read-back. The bot's own words heard back, typed words, and (with
   the voice lock on) another voice are not a yes, and that yes never also approves a waiting permission prompt. The
   same rules as Start and close (`_start_owner_refusal`, `_answer_permission`).
2. **What joins comes from the user's words and the machine's own lists, never from the model.** The brain's tool
   `add_sessions` takes no arguments that are trusted; the daemon re-reads the user's sentence (`guards.attach_request`)
   and searches what the harnesses list.
3. **Only this user's sessions.** Discovery reads the config dirs of this OS user that Pointe already knows (the default
   `~/.claude`, and each `CLAUDE_CONFIG_DIR` a session ever registered with, kept in `accounts.json`). A dir owned by
   another user is skipped; a process the daemon may not signal (another user's) is skipped; a socket is used only when
   it is a socket owned by this user and not a link.
4. **Nothing new leaves the machine, except a short candidate list to the brain when the local match is not sure.**
   That list holds each candidate's title, folder name, age and a few keywords from its user turns (at most 8
   candidates, at most 200 characters each), never a transcript. The vendor is the routing checker that already
   receives session names, folders and recent lines for routing (`_classify_target`), so no new host or vendor is
   added. In fully local mode (`pointe local`) it is the local model.
5. **Reopen opens a terminal, so it is read back as such.** "Reopen billing-migration, the Claude Code session in
   billing from yesterday, in a new terminal window on studio?" Claude Code reopens in its default
   permission mode, never with a skip flag (`refuse_bypass`), Mac only (as Start).
6. **Meeting and Challenge me cannot add sessions** (`modes.READ_ONLY_TOOLS` leaves the tool out).

## Discovery

`Harness.discover(since, cap)` returns `Found` records (`harnesses/base.py`): harness, id, name, folder, state (`open`
or `recent`), when it was last active, branch, title, first and last request, keywords, and per-harness data the
attach needs. The daemon merges this machine's with each paired node's (a `discover` frame, below), drops sessions
already on the voice, and keeps the result for 2 minutes so a tap or a yes acts on what was shown.

Bounds: recent sessions from the last 7 days, at most 40 per account and harness, newest first; at most 64 KB read
from the head and 64 KB from the tail of any transcript. Discovery runs only when asked (the sheet, the voice tool),
never in the background.

### Claude Code

Verified against Claude Code 2.1.330's real output, in an isolated `CLAUDE_CONFIG_DIR` holding only throwaway sessions,
and the docs at code.claude.com (agent view, cross-session messaging, sessions).

| What | Where it comes from | Supported? |
|---|---|---|
| Open sessions | `claude agents --json`, run with the account's `CLAUDE_CONFIG_DIR`: `pid`, `cwd`, `kind` (`interactive`, `background`), `startedAt`, `sessionId`, `name`, `status` (`busy`, `waiting`, `idle`) | Documented: "the supported way to read session state from outside Claude Code" |
| Its inbox socket | `<config>/sessions/<pid>.json`, field `messagingSocketPath`. Checked: the record's `pid` and `sessionId` match the roster's, the path is a Unix socket owned by this user and not a link | **Not** documented as a stable interface. The documented places (`/status`, the `CLAUDE_CODE_MESSAGING_SOCKET` env var of hooks and Bash) are inside the session only. Pointe already reads this file to follow `/clear` and `/resume` (`transcript_path`). Without it, the session is listed and cannot join: "Pointe cannot find how to type into it; run /pointe:voice in it." |
| Its transcript | `<config>/projects/*/<sessionId>.jsonl` | Documented location ("where transcripts are stored") |
| Recent closed sessions | the same `projects/*/*.jsonl`, by modification time; `cwd`, `gitBranch` and the first user turn from the head, the title records (`custom-title`, `agent-name`, `ai-title`) and `last-prompt` from the tail | Documented location; the line shapes are the ones `sessions.py` already reads |

`claude agents --json` is not documented to list interactive sessions in agent view's own sense, but its `--json`
output does list every live session with a pid (seen live), which is what `claude_code.py` already relies on for
`waitingFor`. Background sessions are listed too and join the same way.

**Approvals.** The plugin's `PermissionRequest` hook runs in a session only if the plugin was enabled when that session
started. Pointe tells the user what it can know: the hook applies when `pointe@…` is enabled in the account's
`settings.json` (or managed settings) and not turned off in the folder's `.claude/settings*.json`, or when the
process was started with `--plugin-dir` pointing at Pointe. Otherwise the read-back adds "Its approvals stay in its
terminal." and the session's `capabilities.approvals` is false. A prompt that does stay in the terminal is still seen
through `claude agents --json` (`blocked_on`), as for any joined session.

### Codex

Codex 0.160's app-server schema (`codex app-server generate-json-schema`): `thread/list {limit, sortKey: "updated_at"}`
gives `id`, `cwd`, `name`, `preview` (usually the first user message), `updatedAt`, `status`, `gitInfo.branch`,
`parentThreadId`; `thread/loaded/list` gives the ids the shared daemon has loaded. Open: loaded. Recent: not loaded,
updated in the window. Sub-agent and ephemeral threads are left out. A thread running inside a plain `codex` (not the
shared daemon) is not in the loaded list; joining it fails with Codex's "active writer" error, said as such.

### OpenCode

The service's `GET /api/session?limit=` (every session, newest first) and `GET /api/session/active` (those running a
turn). Every OpenCode session lives on the service and is driven through its API, so there is no closed state to
reopen: sessions updated in the last 2 hours, or active, are listed as open, older ones as recent, and both join the
same way. Child sessions (`parentID`) are left out. Shapes from OpenCode's spec as `harnesses/opencode.py` already
uses them; not run live for this feature.

### Sessions on other machines

New link frames (protocol stays 1; an older node ignores them and the hub says "devbox runs an older Pointe: update
it there"): hub `discover {req, since, cap}`, node `discovered {req, found}`; hub `attach {req, harness, id}`, node
`attach.result {req, ok, why?}`. The node runs the same adapter's `discover` and registers the session in its own
registry, exactly as `/pointe:voice` there would; the session then reaches the hub through the node's `sessions`
snapshot. Reopening a Claude Code session on a node is refused: "Pointe reopens Claude Code sessions only on this Mac for now.
On another machine, resume it there and join it." A recent Codex or OpenCode session there joins through the node.

## Matching a description

`guards.attach_request(text)` reads: the verb (`connect to`, `join`, `attach`, `add`, `listen to`, `bring in` for open
sessions; `reopen`, `resume`, `bring back`, `pick up` for closed ones), "all", a harness ("Claude Code", "Codex",
"OpenCode"), a machine ("on devbox"), a time ("yesterday", "today", "this morning", "last night", "last week",
"recent", "latest") and the rest as the description ("about the billing migration"). A wake phrase ("hey Pointe") is
dropped. The verb must be said, not quoted ("a button saying add session"), with the session word or the agent's name
after it in the same clause: "add speed to the top bar, and tell Claude ..." asks for no session, since an agent told
or asked something is spoken to, not asked for.

`matching.pick(found, ask, now)` then works locally:

1. Hard filters: harness, machine, time, state (a "reopen" looks at recent ones first; a "connect" at open ones only.
   A closed session is offered only when the words ask for one back: "reopen", "bring back", or a past day such as
   "the one from yesterday").
2. Score: each description word against the name and title (3), folder (3), branch (2), first and last request and
   keywords (1), with spoken-name matching as elsewhere (`sessions._hears`).
3. One clear winner (top score at least twice the next): read back that one. "All": read back the count and the names.
   Nothing fits: say so, and name up to three open ones.
4. Close scores between 2 and 8 candidates: the brain ranks them, from titles and keywords only (rule 4). Its answer
   only orders the list; the read-back still decides. Unsure, or the brain unreachable: the voice reads the top 2 or 3
   and asks which.

## The read-backs

Word for word, from `matching.line_one` and `matching.line_all`:

- One open: "Join pentest-recon, the Claude Code session in pentest-notes on studio?"
- One open whose approvals stay in its terminal: "... on studio? Its approvals stay in its terminal. Join?"
- All: "Join 3 open Claude Code sessions on studio: pentest-recon, billing and docs?" (one: "Join the
  one open Claude Code session on studio, pentest-recon? ...")
- Reopen Claude Code: "Reopen billing-migration, the Claude Code session in billing from yesterday, in a new terminal
  window on studio?"
- Reopen Codex: "Reopen invoices, the Codex session in billing from yesterday, on studio?"
- Several fit: "Two sessions fit: one, pentest-recon in pentest-notes, open; two, recon in scanner, from yesterday.
  Which one?" The answer ("the first", "number two", "recon", "both", "neither") is bound to that list.

Spoken requests and their answers are taken by the daemon itself, before the brain (`daemon._attach_words`): the
request is found and read back in the daemon's own words, and the yes, the pick or the no is taken once the read-back
has been spoken. A slow or unreachable brain neither loses nor rewords them (seen live, on a slow network: the brain
timed out on the request and on the yes, and the read-back ran out). The brain's `add_sessions` tool stays for what
reaches the brain anyway (a request inside a longer sentence, a typed one is never a yes). Words that are not a
request, a yes, a no or a pick go to the brain.

Speech splits words ("pen test"): the match also tries each two adjacent words joined, and session names do too
(`sessions._joined`), so "leave the pen test session" leaves pentest-recon.

The read-back shows on every screen as a card with Join (or Reopen) and Cancel; on the iPhone and the Mac the button asks
for Face ID or Touch ID, as Start does. A read-back that asks which one shows a button for each choice ("Join billing",
"Reopen docs"), which posts `{confirm: id, pick: key}`; a key that was not read back joins nothing.

## Attach

`Harness.attach_body(found)` returns the `/voice/register` body, the same one the session would send itself:

| Harness | Body |
|---|---|
| Claude Code | `id` (sessionId), `name` (its Claude Code name; a user-given one is kept), `cwd`, `pid`, `transcript`, `inbox_socket`, `config_dir`. No inbox token: it is optional on macOS and Linux (docs), and the daemon was never the session's child anyway. |
| Codex | `id` (thread id), `cwd`, `transcript` (the mirror), `harness_data.title`; `watch` resumes the thread |
| OpenCode | `id`, `cwd`, `transcript` (the mirror), `harness_data.title` |

The daemon registers it through `_join` with `attached: true`: a Claude Code session attached from outside is not in a
turn of its own, so its first report is news (`joining` is false). Watch, send, notes, briefings and approvals work as
for any joined session.

**Detach** is the existing close: "leave the pentest session", "disconnect from the pentest session", "drop pentest".
The session keeps running where it is.

## Reopen

| Harness | How | Platform |
|---|---|---|
| Claude Code | Start's mechanism with `--resume <id>`: a `.command` script in a new Terminal (or iTerm) window runs `claude --resume <id> --permission-mode default --settings <file>` in the session's folder, with `CLAUDE_CONFIG_DIR` set for a second account. The settings file's `SessionStart` hook (matcher `resume`) runs `bin/register-session --start <id>`; the start record checks the harness, the folder and the session id. | Mac only |
| Codex | `thread/resume` on the shared daemon (what attach does): the thread is loaded again and joins; the user types into it with `codex resume <id> --remote unix://`. A thread that comes back with approvals `never` and sandbox `dangerFullAccess` is refused, as at Start. | any hub |
| OpenCode | the same as attach | any hub |

A session that is open already is joined, not reopened. A folder that is gone cannot be reopened (said so).

## Interfaces

- Brain tool `add_sessions` (no trusted arguments).
- `GET /voice/add-sessions`: `{machines: [{name, here, online, why}], open: [...], recent: [...], reopen_here}`; each
  item `{key, machine, harness, label, name, folder, path, state, when, branch, title, first, last, approvals,
  joinable, why}`.
- `POST /voice/add-sessions`: `{join: [key, ...]}`, `{reopen: key}`, `{confirm: id}`, `{cancel: id}`. Keys come from
  the last listing; a key that is not in it is refused (409).
- `/voice/status`: `attach_pending` (`{id, line, verb}`) while a read-back waits.
- Adapter contract (`docs/harnesses.md`): `discover`, `attach_body`, `reopen`, `hook_applies`.

## Not in this version

Reopening a Claude Code session on a node; picking which account a reopened Claude Code session runs in (it is the account it ran in);
OpenCode's TUI opened for the user; sessions of Claude Code on the web or Codex Cloud ([cloud-sessions.md](../cloud-sessions.md)).
