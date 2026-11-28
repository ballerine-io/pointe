# Start a new session from Pointe

Decided 2026-11-21, for 1.16.0. Roadmap issue #18, "start new agents by voice". Until now a session reached the voice
only after a person started it in a terminal and ran `/pointe:voice` or `pointe join <harness>`. This adds the other
direction: Pointe starts the session, by voice or from a "New session" sheet on the page, the iPhone app and the Mac
app, and it joins the voice by itself.

It widens what the voice can do: a spoken sentence can now create a process that edits files. So the rules come first,
and each one is in code with a test (`newsession.py`, `guards.start_request`, `tests/test_new_session.py`).

## The rules

1. **Only folders the user already works in.** The folder is picked from a list the daemon builds, never from a path
   in the request: folders of sessions on the voice now, folders of sessions that joined in the last 30 days
   (`folders.json`), and folders the user added in Settings (`sessions.folders`). Speech picks one by its name, as it
   picks a session; a name two folders answer to is a tie, and the voice asks which. A path that is not in the list is
   refused whatever surface sent it, and a folder that no longer exists is not offered.
2. **The list is changed only at the Mac.** `sessions.folders` is refused from the phone's key and from a page opened
   over the network: a lost phone cannot add a folder and then start an agent in it.
3. **Skip prompts only by the setting, and only for a new Claude Code session.** Changed 2026-11-25 by the owner's
   decision (SECURITY.md): the setting "Permissions for new sessions" (`sessions.permissions`) defaults to Skip
   permission prompts, and a new Claude Code session then starts with `--permission-mode bypassPermissions`
   (`claude_code.SKIP_ARGS`); with Ask before actions, or "asks first" in the request, it starts with
   `--permission-mode default` as before. The flag is said outright either way: it wins over a `defaultMode` in the
   user's settings. Claude Code's one-time check before skipping is never left in a terminal: Pointe reads whether it
   was accepted (`claude_code.skip_check`), asks the user in the read-back when it was not, and passes the yes in the
   session's own `--settings` file, never in the user's settings. A reopen, a night shift's session, Codex and
   OpenCode never skip. A Codex thread that comes back with approvals `never` and sandbox `dangerFullAccess` (the
   user's own config says so) is archived at once and the start is refused with the reason.
   `harnesses.base.refuse_bypass` checks every command line and request a starter builds, all but the one mode the
   setting chose.
4. **Pointe's approval rules apply as for a joined session.** A started session is an ordinary session of its
   harness: the same adapter, the same read-out, the same bound yes, the same taps.
5. **A read-back, bound to the user's own words.** By voice nothing starts on the first sentence. The daemon reads
   back exactly what it will start ("Start a Claude Code session in shop on studio, named shop-2?"; "on studio" only
   when another machine is paired, since a default host name holds the owner's first name)
   and starts it on the user's next plain yes within 60 seconds, as close-by-voice does (`disconnect_session`). The
   harness, folder, machine and name come from the user's words (`guards.start_request`), never from the model's
   arguments. The bot's own read-back heard back is not a yes; typed words are not a yes; with the voice lock on, only
   the owner's voice is; the yes that starts a session never also approves a waiting permission prompt.
6. **A tap is explicit.** The sheet has its own Start button. The read-back also shows as a card with Start and
   Cancel; on the iPhone and the Mac, Start asks for Face ID or Touch ID, as Approve does.
7. **Meeting and devil's-advocate modes cannot start anything** (`modes.READ_ONLY_TOOLS` leaves the tool out).

## How each harness starts

Checked against the installed tools (Claude Code 2.1.330, OpenCode 2.0.27, Codex 0.171 app-server) and their own
descriptions of their interfaces (`claude --help`, OpenCode's `/openapi.json`, `codex app-server generate-json-schema`).

| Harness | Mechanism | The user can type into it | Joins by |
|---|---|---|---|
| Claude Code | A new terminal window runs `claude --permission-mode bypassPermissions --name <name> --settings <file>` in the folder (`default` with Ask before actions; then, should Claude Code end before its session starts, the script runs it again with `default`). Pointe writes a small `.command` script under its state dir and opens it with `open -a Terminal` (iTerm when it is the terminal running). | Yes: it is a real terminal session. | A `SessionStart` hook in that settings file runs `bin/register-session --start <id>`. The hook's environment carries the session's inbox socket (verified live), so it joins in attach mode: no channel, no development flag, no Node. |
| OpenCode | `POST /api/session {location: {directory}, title}` on its local service | Yes, after `opencode --session <id>` in the folder: the TUI is a client of the same service. | The daemon registers it from the answer. |
| Codex | `thread/start {cwd}` on the shared app-server daemon, then `thread/name/set` | Yes, after `codex resume <id> --remote unix://`. | The daemon registers it from the answer. |

Why a terminal window for Claude Code and not launch mode or a pty. Launch mode (`bin/claude-voice`) needs
`--dangerously-load-development-channels`, which stops at a warning the user must answer, and Node. A detached pty
gives the user nothing to type into. A window opened with `open` is the user's own terminal, and `open` needs no
Automation permission (an AppleScript `tell application "Terminal"` raises a system prompt the first time, which a
daemon cannot answer). A shell alias for `claude` (some add the skip-permissions flag) does not apply inside the
script.

Claude Code asks "do you trust this folder" the first time it runs in one, before any hook. A folder the user already
runs Claude Code in is past that; in another (one only OpenCode ran in), the session waits in its window and Pointe
says so.

## Machines

A start runs on the Mac the daemon runs on, or on a machine somebody invited this voice to
([people-and-machines.md](people-and-machines.md), "Phase 3"): there the link carries `folders`, `start` and
`start.result`, and that machine's own folder list is the authority (a voice never names a path the machine did not
list). `GET /voice/new-session?machine=<name>` is that machine's list. A machine of the user's own that is a node
has no start yet: asking for it by voice is refused with one line, and the sheet shows it as not available.

## Names, collisions, failures

- **Name.** The one the user gave, else the folder's name; if a session already has it, `-2`, `-3` (what the registry
  does for any join). The read-back says the final name, and the session joins with exactly that name: it is
  registered as named by the user, so a title from the harness never replaces it. A given name must pass the rename
  rules (speakable, not a machine's name, no yes or no word, not taken).
- **In the list.** From Start until it joins, `/voice/status` carries it in `starting` (`name`, `harness`, `folder`,
  `state`: `starting`, `waiting`, `failed`; `detail`), and every surface shows a row under the sessions. When it
  joins, the row becomes the session. A failed start stays for two minutes with its reason.
- **Failures**, each with fixed words: the harness is not installed; OpenCode's service or Codex's daemon is not
  running (with the command that starts it); the folder is gone; the folder is not in the list; the name is not
  usable; no terminal can be opened (on Linux: tmux is missing or not working); Claude Code has not joined after 90 seconds (the window is open: it
  may be asking something there); the harness would bypass.
- **The first prompt** (the sheet only, up to 4,000 characters) is sent after the session is on the voice, through
  the same `send` as any request. If the session never joins, it is not sent, and the failure says so. By voice there
  is no first prompt in this version: the next sentence ("tell shop-2 to ...") is an ordinary send.
- **No worktree option.** Creating a git worktree means choosing a branch and a place for it; not trivial, deferred.

## Interfaces

- `GET /voice/new-session`: `{harnesses: [{name, label, agent, available, why}], machines: [{name, here, available,
  why}], folders: [{path, name, source}], pending}`.
- `POST /voice/new-session`: `{harness, folder, name?, prompt?, machine?}` starts; `{confirm: id}` starts what was
  read back; `{cancel: id}` drops it. Answers `{id, name}` or 4xx with the reason in `detail`.
- `/voice/status`: `starting` (above) and `start_pending` (`{id, line, harness, folder, name}` while a read-back
  waits).
- The brain's tool `start_session` (no arguments are trusted).
- `Harness.starts`, `Harness.start(cwd, name, start_id)`, `Harness.open_hint(session)` (`harnesses/base.py`).
- `sessions.folders` in prefs: absolute paths, at most 50.

## Not in this version

Starting on a node; a new git worktree; a first prompt by voice; picking the Claude account (a started session runs in
the terminal's default account); terminals other than Terminal and iTerm. (Claude Code now starts on a Linux hub, in tmux.)
