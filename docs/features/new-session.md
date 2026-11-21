# Start a new session

Pointe can start a coding agent for you, in a folder you already work in, instead of you opening a terminal first. The
session joins the voice by itself. Design and reasons: [docs/design/new-session.md](../design/new-session.md).

The rules live in `newsession.py` (where a session may start, names), `guards.start_request` (what your words ask for),
`daemon.start_session` (the read-back and the yes) and each harness's `start` (`harnesses/`).

## Use it

- **Voice:** "start a new Claude Code session in shop", "open a codex session in billing called invoices", "start
  another agent here". Pointe reads back exactly what it will start ("Start a Codex session in billing on studio, named
  invoices? Say yes or tap.") and starts it on your yes. Say no, or anything else, and nothing starts. With no agent
  named it is Claude Code.
- **Page:** New session under the sessions on the left. Pick the agent and the folder, give it a name and a first
  prompt if you like, press Start.
- **iPhone app:** Sessions, then New session. Start asks for Face ID, as Approve does.
- **Mac app:** New session in the window's sessions list. Start asks for Touch ID or your password.

The new session shows under your sessions as "starting" until it joins, then it is a session like any other. If it
cannot start, the row says why for two minutes (the agent is not installed, its service is not running, the folder is
gone).

## What starts

| Agent | What Pointe does | Where you can type into it |
|---|---|---|
| Claude Code | opens a new terminal window (Terminal, or iTerm when that is the one running) with `claude` in the folder | that window |
| OpenCode | creates the session on OpenCode's local service | `opencode --session <id>` in the folder |
| Codex | starts a thread on Codex's shared daemon | `codex resume <id> --remote unix://` |

The first time Claude Code runs in a folder it asks whether you trust it, in its window, before it joins.

## What it will not do

- **Start anywhere else.** Only folders of your current sessions, of sessions that joined in the last 30 days, and
  folders you added in Settings → New sessions. A path is never taken from speech, and the list is changed only on the
  Mac, never from the phone.
- **Skip permission prompts.** Claude Code starts with `--permission-mode default`; OpenCode and Codex start in their
  own default. A Codex configuration that runs with no approvals and no sandbox is refused. A started session's
  prompts are read out and answered as any session's.
- **Start on a guess.** Two folders with the same name, or a name it did not catch: it asks which. The yes must be
  yours: the read-back heard back, typed words, and (with the voice lock on) another voice do not count, and that yes
  never also approves a waiting request.
- **Start in a meeting or in Challenge me.** Those modes cannot act.
- **Start on another machine.** This version starts sessions on the Mac Pointe runs on. On a node, start it there and
  join it.

The first prompt is sent only after the session is on the voice. By voice there is no first prompt: say the request
next ("tell invoices to list the open ones").
