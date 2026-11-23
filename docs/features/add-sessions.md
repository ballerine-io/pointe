# Add sessions

Pointe can join sessions you already run, or bring back one you ran this week, without anyone typing `/pointe:voice` in
them. Describe them, and Pointe finds them, reads back what it found, and joins them on your yes. Design and reasons:
[docs/design/attach-by-voice.md](../design/attach-by-voice.md).

The rules live in `discovery.py` (what is listed), `matching.py` (which sessions your words mean, and the read-backs),
`guards.attach_request` (what your words ask for) and `daemon.add_sessions` (the read-back and the yes).

## Use it

| Say | Pointe says | On yes |
|---|---|---|
| "Hey Pointe, connect to the session about the recent pentest" | "Join pentest-recon, the Claude Code session in pentest-notes on studio?" | it joins |
| "Connect to all open Claude Code sessions" | "Join 3 open Claude Code sessions on studio: pentest-recon, billing and docs?" | they all join |
| "Reopen yesterday's session about the billing migration" | "Reopen billing-migration, the Claude Code session in billing from yesterday, in a new terminal window on studio?" | a terminal window opens with `claude --resume`, and it joins |
| "Join the codex thread about the changelog" | "Join docs, the Codex session in docs on studio?" | it joins |
| "Connect to a session" (several fit) | "Three sessions fit: one, …; two, …; three, …. Which one?" | "the second one", "both", or a name |
| "Leave the pentest session", "disconnect from the pentest session" | (no read-back for one named session) | it leaves the voice and keeps running |

Also: "join the pentest session on devbox", "resume the codex thread from this morning", "bring back the last session",
"listen to the docs agent", "add all opencode sessions".

- **Page:** Add sessions under the sessions on the left. Open sessions are ticked and joined together; a session from
  this week has Reopen. Search by name, folder or what you asked it.
- **iPhone app:** Sessions, then Add sessions. Join and Reopen ask for Face ID, as Approve does.
- **Mac app:** Add sessions in the window's sessions list, or Add Sessions in the File menu (⇧⌘J). Join and Reopen ask
  for Touch ID or your password.

## What it finds

| Agent | Open now | This week |
|---|---|---|
| Claude Code | every live session `claude agents --json` lists, in each Claude account Pointe knows | closed transcripts, reopened with `claude --resume` in a new terminal window (Mac only) |
| Codex | threads loaded by Codex's shared daemon (a TUI started with `codex --remote unix://`) | other threads, loaded again on the shared daemon |
| OpenCode | sessions running a turn, or touched in the last two hours | older sessions on OpenCode's service; joining one is the same as joining an open one |

Sessions on your other machines are listed too, through their Pointe node. A Claude Code session on another machine is
not reopened from here: resume it there and join it.

## Approvals

Codex and OpenCode prompts reach the voice through their services, as for any joined session. A Claude Code session
sends its prompts to the voice only if Pointe's plugin was on when it started (the plugin's `PermissionRequest` hook).
Pointe checks the settings it can see; where the hook does not apply, the read-back and the screens say "Its approvals
stay in its terminal", and the voice tells you when that session waits there.

## What it will not do

- **Join anything you did not confirm.** A description only finds and reads back. A yes, a pick from the list read
  back, or a tap joins. The yes and the pick keep a permission prompt's rules: a yes and nothing else, begun after the
  read-back ended, with the read-back the last thing Pointe said. The read-back heard back, typed or corrected words,
  and (with the voice lock on) another voice do not, and that yes never also approves a waiting prompt.
- **Read another user's sessions.** Only this OS user's config dirs, processes and sockets.
- **Send your sessions to a vendor.** Matching is done on this Mac. When the words fit a few sessions about as well,
  their titles, folder names, ages and a few keywords (never transcripts) go to the routing model to order them, which
  already sees session names for routing. In fully local mode that is the local model.
- **Add sessions in a meeting or in Challenge me.** Those modes cannot act.
