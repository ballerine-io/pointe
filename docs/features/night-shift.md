# Night shift

In the evening you give Pointe tasks for your sessions. It reads the plan back, starts on your yes, keeps the sessions
moving while you sleep, and the morning briefing leads with what was decided without you and what waits on you. Pointe
approves nothing at night: a session that needs approval waits for you. Design and reasons:
[docs/design/night-shift.md](../design/night-shift.md).

The rules live in `nightshift.py` (what your words ask for, the only messages a shift sends, what a report means, the
caps, the ledger, the morning report); `daemon.py` runs the shift, holds the approvals and builds the briefing.

## Use it

- **Voice:** "Tonight: billing finishes the retry work and opens a PR; docs updates the changelog; start a Codex session
  in shop to fix the flaky test." Each session gets the words you said after its name. Pointe reads the plan back
  ("Night shift. billing: finishes the retry work and opens a PR. … Up to 8 hours and 40 messages. I approve nothing: a
  session that needs approval waits for you. Start? Say yes or tap.") and starts on your yes. Say no, or anything else,
  and nothing starts.
- **Page:** Night shift under the sessions on the left. One row per task: the session (or New session, with its agent
  and folder) and what it should get done. Set the hours, the message budget and whether blockers may alert you
  overnight, then Start shift.
- **iPhone and Mac apps:** Night shift in the Settings (⋯) menu, the same sheet. Start shift asks for Face ID or Touch
  ID, as Approve does.
- **While it runs:** a strip shows tasks done, the blocked count and Stop shift; Ledger opens the night's record.
- **Stop:** "stop the night shift", or Stop shift on any screen. Pointe sends nothing more. A turn already running in a
  session finishes by itself.
- **Morning:** "brief me on the night" (or the scheduled briefing) starts with the night shift: decisions made without
  you, questions waiting on you, then done and blocked. "Approve billing's push" makes billing the active session and
  reads its exact request out; your yes after that, or a tap, answers it. "Tell docs to use the old format" is an
  ordinary request, and answers docs' question on the ledger.

## What happens overnight

Each session gets its task inside a fixed night brief: keep going on what is not blocked, do not stop to ask (choose the
most defensible answer and write it down), do nothing destructive or outward-facing beyond the task, leave anything
that needs your approval, and end with a short report (`STATUS`, `DONE`, `BLOCKED`, `DECIDED`).

| The session | Pointe |
|---|---|
| reports done | records it with the proof line, and any commit or pull request found in the message; sends its next task |
| reports blocked | records what it waits on; moves it to its next task |
| asks a question | records the question; tells it to decide itself and write down the choice and what changes otherwise |
| stops with no report | asks for one |
| goes quiet for 10 minutes while idle | asks for its status, once |
| asks for a permission | holds the request, unanswered, and records it word for word as Blocked |
| closes | records it; its remaining tasks are not started |

A task gets at most 3 follow-ups; after that it is recorded as Blocked and the session moves on. Every message Pointe
sends at night is one of five fixed texts around your own task; no model writes one.

## The ledger

Four buckets, kept in `~/.claude-voice/night-shifts.json` (0600) for the last seven shifts, with credentials masked:

- **Done**: what was finished, the session's own proof line, the commit or pull request when it named one.
- **In flight**: what is still being worked on.
- **Blocked**: what waits and on whom; for an approval, the exact request.
- **Decided / asked**: the question, what was chosen, and what changes if you choose otherwise.

## What it will not do

- **Approve, or deny.** A permission request from a session on the shift is never answered by Pointe. It is held for up
  to 12 hours and waits for you; you can also answer it in the session's own terminal.
- **Widen what a session may do.** No permission mode is changed and no rule is added. A new session on the plan starts
  as New session starts one: in a folder you already work in, never with prompts skipped.
- **Start without your yes.** The read-back heard back, typed words and, with the voice lock on, another voice do not
  count, and that yes never also approves a waiting request.
- **Run past its caps.** 8 hours and 40 messages unless you set otherwise (at most 12 hours, 200 messages). The
  sheet is where you set them: what a shift started with there is what the next one starts with, by voice too. Past a cap it sends nothing more.
- **Wake you.** A shift's blockers raise no alert on the phone, the watch or the desktop unless you turn on "Alert me
  about blockers overnight". They alert as usual once you are back.
- **Run in a meeting, in Challenge me or during a brain dump**, or two shifts at once.
- **Drive a session on another machine.** This version runs sessions on the Mac Pointe runs on.

## Limits

- Stop ends the sending; it does not interrupt a turn that is already running.
- The budget counts messages, not tokens or money: Pointe does not see what a session spends.
- A request Claude Code shows only in its terminal (a launch-mode prompt, or `approvals: terminal` in the config) is
  recorded as "a permission prompt in its terminal", without its text.
- A session's report is read by its labels. A session that ignores the format is asked again, then recorded as Blocked
  with its last line.

## API

All reachable with the page cookie, the bearer token and the phone key.

| Route | Body | Returns |
|---|---|---|
| `GET /voice/night-shift` | `?id=` for one of the last seven | `{shift, history, caps, limits, rule, pending, sessions}` |
| `POST /voice/night-shift` | `{action: start, items: [{session, task} \| {start: {harness, folder, name?}, task}], hours?, messages?, notify?}` | `{started, shift}`; 409 while one runs, in a meeting or a challenge; 400 or 403 with the reason in `detail` |
| `POST /voice/night-shift` | `{action: confirm \| cancel, id}` | starts or drops what was read back |
| `POST /voice/night-shift` | `{action: stop}` | `{stopped, shift}`; 409 when none runs |

`/voice/status` carries `night_shift` (the running or last shift in short) and `shift_pending` (a read-back that waits).
Settings: `nightshift.hours`, `nightshift.messages`, `nightshift.notify`.
