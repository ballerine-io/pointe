# Start a new session

Pointe can start a coding agent for you, in a folder you already work in, instead of you opening a terminal first. The
session joins the voice by itself. Design and reasons: [docs/design/new-session.md](../design/new-session.md).

The rules live in `pointe/newsession.py` (where a session may start, names), `guards.start_request` (what your words ask for),
`daemon.start_session` (the read-back and the yes) and each harness's `start` (`pointe/harnesses/`).

## Use it

- **Voice:** "start a new Claude Code session in shop", "open a codex session in billing called invoices", "start
  another agent here". Pointe reads back exactly what it will start ("Start a Codex session in billing on studio, named
  invoices?"; the machine is named only when another one is paired) and starts it on your yes, or a tap on Start. Say no, or anything else, and nothing starts. With no agent
  named it is Claude Code.
- **Page:** New session under the sessions on the left. Pick the agent and the folder, give it a name and a first
  prompt if you like, press Start.
- **iPhone app:** Sessions, then New session. Start asks for Face ID, as Approve does.
- **Mac app:** New session in the window's sessions list (in a narrow window, under Sessions), New Session in the File
  menu (⌘N), or New Session in the menu bar item's menu. Start asks for Touch ID or your password. Settings → New
  sessions lists the folders you added, with Add a folder… and Remove.

The new session shows under your sessions as "starting" until it joins, then it is a session like any other. If it
cannot start, the row says why for two minutes (the agent is not installed, its service is not running, the folder is
gone).

## Permissions for new sessions

**A new Claude Code session that Pointe starts skips permission prompts by default.** It can edit files and run
commands without asking you first, so there are no requests to approve, by voice or otherwise. This is the owner's
choice for Pointe ([SECURITY.md](../../SECURITY.md#starting-a-session)). If you want to approve each action, choose Ask
before actions.

| Setting | What Claude Code starts with | Requests to approve |
|---|---|---|
| **Skip permission prompts** (default) | `--permission-mode bypassPermissions` | None. Claude Code still prompts for the few actions no mode approves by itself (an explicit `ask` rule, removing a critical path such as your home folder). |
| **Ask before actions** | `--permission-mode default`, as before | Each one, read out and answered by voice or a tap. |

- **Change it:** Settings → Permissions for new sessions, on the page, the iPhone app and the Mac app. By voice: "new
  sessions ask first" or "new sessions skip permission prompts". With the voice lock on, only your voice can turn
  skipping on; any voice can turn it off.
- **One session that asks first:** "start a session in shop that asks first", or "… in safe mode". The read-back says
  "asking before actions". When Pointe reads back a session that would skip prompts, you can also answer "ask first".
  ("Safe mode" here means Pointe's Ask before actions, not Claude Code's own `--safe-mode`.)
- **The risk is said once.** The first time a session starts skipping prompts, Pointe says: "New sessions skip
  permission prompts: they can edit files and run commands without asking. Say “ask first”, or change it in Settings."
  The line shows in the read-back and under the starting session, then never again.

### The first time on a Mac

Before a session can skip prompts the first time, Claude Code asks you once, in its own terminal, to accept the risk.
A session started by voice may have nobody at that terminal. Pointe never leaves the session waiting there:

1. Pointe reads Claude Code's settings (`skipDangerousModePermissionPrompt` in `~/.claude/settings.json` or in managed
   settings). If you already accepted it in Claude Code, nothing more is asked.
2. If not, the read-back asks for it plainly: "Start a Claude Code session in shop, named shop-2, skipping permission
   prompts? Claude Code needs your consent once for that: new sessions can then edit files and run commands without
   asking. To keep its prompts, say “ask first”. Start it skipping them?" A yes (or Start on the card) starts it
   skipping prompts and is kept, so Pointe does not ask again. "Ask first" starts that session asking. No, or no
   answer in 60 seconds, starts nothing.
3. Pointe passes your yes to Claude Code in that session's own settings file (`--settings`). It never writes your
   Claude Code settings.
4. From the New session sheet, which cannot show the question, a session that still needs your consent starts asking
   before actions. Start one by voice, or tap Start on the read-back card, to give it.
5. If Claude Code ends before its session starts (a policy Pointe cannot read turns the mode off), the same terminal
   starts it again asking before actions, at once.

When Claude Code's settings turn the mode off (`permissions.disableBypassPermissionsMode`), the session asks before
actions and Pointe says so.

### What this does not change

- **Sessions you already run.** Joining or reopening a session never changes its permission mode. A reopened Claude
  Code session resumes with `--permission-mode default`.
- **OpenCode and Codex.** They start in their own default; Pointe never skips their prompts.
- **A night shift.** Its new sessions always ask: a shift holds every request for the morning.
- **Voice approvals.** In a session that asks, Pointe reads out each request and takes your yes, as before.

## What starts

| Agent | What Pointe does | Where you can type into it |
|---|---|---|
| Claude Code | opens a new terminal window (Terminal, or iTerm when that is the one running) with `claude` in the folder, in the mode your setting says | that window |
| OpenCode | creates the session on OpenCode's local service | `opencode --session <id>` in the folder |
| Codex | starts a thread on Codex's shared daemon | `codex resume <id> --remote unix://` |

The first time Claude Code runs in a folder it asks whether you trust it, in its window, before it joins.

## What it will not do

- **Start anywhere else.** Only folders of your current sessions, of sessions that joined in the last 30 days, and
  folders you added in Settings → New sessions. A path is never taken from speech, and the list is changed only on the
  Mac, never from the phone.
- **Skip prompts outside the setting.** Only a new Claude Code session skips them, and only with the setting on Skip
  permission prompts. OpenCode and Codex start in their own default; a Codex configuration that runs with no approvals
  and no sandbox is refused. In a session that asks, prompts are read out and answered as any session's.
- **Start on a guess.** Two folders with the same name, or a name it did not catch: it asks which. The yes must be
  yours, under the rules of a yes to a permission prompt: a yes and nothing else ("okay, except in billing" is not one),
  begun after the read-back ended, with the read-back the last thing Pointe said. The read-back heard back, typed or
  corrected words, and (with the voice lock on) another voice do not count, and that yes never also approves a waiting
  request.
- **Start in a meeting or in Challenge me.** Those modes cannot act.
- **Start on a machine of your own that is a node.** Start it there and join it. On a machine somebody invited you
  to, you can start one if you may send there: [a shared machine](../multi-machine.md#starting-a-session-on-a-shared-machine).

The first prompt is sent only after the session is on the voice. By voice there is no first prompt: say the request
next ("tell invoices to list the open ones"). Right after it joins, "rename it to shop-tests" renames the new session,
not the active one; after a switch, "it" is the session you switched to again.
