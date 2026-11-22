# Night shift

Decided 2026-11-22, for 1.19.0. In the evening the user gives Pointe tasks for their sessions; Pointe reads the plan
back, starts on a yes, keeps the sessions moving while the user sleeps, and the morning briefing leads with what was
decided without them and what waits on them.

It is built on the owner's own night-shift practice: keep going on any front that is not blocked; park what is blocked
and jump to something else; never stop for a question (record it with the assumption taken); keep a ledger with Done,
In flight, Blocked and Decided / asked; and leave a morning report that leads with the decisions made and the questions
waiting. The safety rails of that practice are absolute, and here they are code.

This widens what Pointe does more than any feature before it: it sends to sessions while nobody is listening. So the
rules come first, each one in code with a test (`nightshift.py`, `daemon.py`, `tests/test_night_shift.py`).

## The rules

1. **A shift starts only on the user's own yes to a read-back.** By voice the sessions, the tasks and any new session
   are taken from the user's own words in code (`nightshift.plan_request`), never from the model's arguments. Each task
   is a span of what the user said, word for word. The daemon reads the plan back, with the caps and the approval rule,
   and starts on the next plain yes within 60 seconds, as a new session does: the bot's read-back heard back is not a
   yes, typed words are not a yes, with the voice lock on only the owner's voice is, and that yes never also approves a
   waiting permission prompt. On a screen, Start is its own button; the apps ask for Face ID or Touch ID.
2. **Pointe never answers an approval, at night or ever.** A permission request from a session on the shift is never
   auto-approved and never auto-denied. It is held, unanswered, and the ledger gets a Blocked entry with the exact
   request. The session waits there; its other tasks wait behind it. The user answers it in the morning through the
   normal flow: the request read out exactly, then their yes or a tap. No code path in `nightshift.py` or the shift's
   part of `daemon.py` can call `_apply_answer`; a test checks that.
3. **Every message a shift sends is a fixed template.** The model writes no send at night. A session gets the user's
   task inside the night brief, and after that only one of four fixed follow-ups (continue, decide it yourself, report,
   status). None of them grants anything: each repeats that nothing destructive or outward-facing beyond the task may be
   done and that a step needing approval is to be left and listed.
4. **A session may do only what it already may.** A shift changes no permission mode, adds no allow rule, and starts a
   new session exactly as New session does: in a folder the user already works in, in the harness's default permission
   mode, never one that skips prompts (`_check_start`, `harnesses.base.refuse_bypass`).
5. **Caps.** A shift ends after its hours (default 8, at most 12), and sends at most its message budget (default 40
   messages to sessions, at most 200), with at most 3 follow-ups per task. Past a cap Pointe sends nothing more; what is
   running finishes its turn and is recorded. Both caps are settings (`nightshift.hours`, `nightshift.messages`), set in
   the sheet: what a shift started with there is kept, and is what a shift started by voice uses. At most 8 sessions and 5 tasks per session.
6. **The user can stop it at any time.** "Stop the night shift" by voice (a no needs no read-back, and counts from any
   voice, as a no to a prompt does), or Stop on any screen. After a stop Pointe sends nothing more. A turn already
   running in a session finishes on its own: Pointe does not interrupt an agent mid-edit.
7. **Read-only modes cannot start one.** Not in a meeting, in Challenge me or while thinking out loud; the tool is not
   in `modes.READ_ONLY_TOOLS`.
8. **This Mac only.** A shift drives sessions on the Mac Pointe runs on. A session on another machine is refused in the
   read-back with one line (a node forwards its prompts only while a call is up, so it could not be parked).
9. **Quiet by default.** A shift's blockers raise no alert on the phone, the watch or the desktop unless
   `nightshift.notify` is on (off by default). They are in the ledger and in the morning briefing either way.

## What the user says

- "Tonight: billing finishes the retry work and opens a PR; docs updates the changelog; start a Codex session in shop
  to fix the flaky test."
- "Night shift: have billing fix the retry tests, then docs should update the changelog."
- Hebrew: "הלילה: billing יסיים את ה-retry ויפתח PR".

`nightshift.shift_intent` takes an utterance that opens with "tonight", "for tonight", "overnight", "night shift" or
"on the night shift" (after "ok", "Pointe"). `plan_request` then cuts the rest into items:

- An item starts where a session's name is said at the head of a clause (after the opening, or after `;`, `.`, `,`,
  "and", "then", "also"), optionally after "tell / ask / have / let / get", and runs to the next head. The name is
  matched as every spoken session name is (`sessions._hears`), and the item's task is the words after it, as said,
  with a leading "to / should / will / can / please" dropped. "billing finishes the retry work and opens a PR" is one
  task: "and opens" names no session.
- A clause that asks for a new session (`guards.start_request`) is a start item: the agent, the folder and the name
  come from the words as for New session, and the task is what follows "to" after the place.
- A name two sessions answer to, a session on another machine, an item with no task, a start with no folder or a tied
  folder: the plan is not read back; Pointe asks about that one thing.
- A second item for the same session queues behind the first.

The read-back (`nightshift.read_back`) is fixed words: "Night shift. billing: finish the retry work and open a PR.
docs: update the changelog. A new Codex session in shop, named shop-2: fix the flaky test. Up to 8 hours and 40
messages. I approve nothing: a session that needs approval waits for you. Start? Say yes or tap."

A plan and the yes or no after its read-back are taken in code (`daemon._night_words`, in the ears, before the model):
the daemon speaks the read-back itself, so the line the user hears is the line a yes starts. In the first live run the
model answered a long plan eight seconds late, with nothing; a rule that starts unattended work cannot hang on that.
The brain's `night_shift` tool stays, for wordings the opening does not catch, and both paths run the same two
functions (`_shift_ask`, `_shift_answer`).

## The loop

One shift at a time. Each session on it is a front with a queue of tasks. `nightshift.step` is a pure function from
(front, what happened, caps, now) to an action; `daemon.py` only carries the action out.

The night brief (the first message of every task) tells the session the night's rules and asks it to end its turn with
a fixed block:

```
NIGHT REPORT
STATUS: done | blocked | working
DONE: what was finished, with the proof (commit, pull request, test output)
BLOCKED: what waits, and on whom
DECIDED: the question -> what was chosen -> what changes if the user chooses otherwise
```

So the session itself, which has the context, makes each judgment call and writes down the question, the choice and
its cost. Pointe never invents an answer to a session's question.

When a session on the shift ends a turn (`daemon.feed`, with or without a call up):

| What its message says | Ledger | Next |
|---|---|---|
| `STATUS: done` | Done, with the DONE line as proof and any commit hash or pull request found in the message by a regex; each DECIDED line as a decision; each BLOCKED line as a blocker | its next task, or the front is finished |
| `STATUS: blocked` | Blocked: what and on whom | park the task, jump to its next task |
| `STATUS: working` | nothing | the *continue* follow-up |
| no block, and it asks the user something (the report digest says it waits, or its last lines are a question) | Asked: the question, "left to the session" | the *decide it yourself* follow-up; its DECIDED line then replaces the entry |
| no block, no question | nothing | the *report* follow-up |
| follow-ups for the task used up | Blocked: "did not finish in N follow-ups", with its last line | park, jump |

Between turns the keeper (`daemon._night_keeper`, every 10 s) looks at each front:

- **A permission request is pending** (held by Pointe, or a prompt in its terminal that Pointe cannot see into):
  Blocked, with the exact request when Pointe holds it. Nothing is sent to that session until it is answered.
- **Stalled**: a task is in flight, the session is idle and no report has come for 10 minutes (the turn end was missed,
  or the agent stopped without the block): the *status* follow-up, once per stall, within the follow-up cap.
- **Gone**: the session left the voice or its process exited: Blocked ("the session closed"), the front is parked.
- **Not delivered** (the harness refused or held Pointe's message): Blocked with the fixed reason, parked.
- **Caps**: past the hours the shift ends; past the message budget nothing more is sent and the shift ends when the
  running turns have reported.
- **Complete**: every front is finished or parked: the shift ends.

With no call up nothing follows the sessions' transcripts, so the keeper runs each front's harness watcher itself
(`Harness.watch`), and hands it back when a call's own workers take over.

A new session on the plan is started with `begin_start`; its first task goes out when it joins. If it does not join,
that front is Blocked with the start's own reason.

## Approvals at night

`hold_permission` gains one case. For a session on a running shift the request is held with no call up (today the hook
answers nothing and the prompt goes to the terminal at once), with no speech, and for as long as 12 hours instead of
280 seconds. The user can still answer it at the session's own prompt. `_hand_prompts_back` (a call ended) leaves it
held. The ledger's Blocked entry carries the request as the approval card shows it (`permission_full`, masked).

Claude Code's hook is a process that waits on the daemon, so `hooks/hooks.json` raises its timeout to 12 h 5 min and
`bin/voice-permission-hook` its `curl --max-time` to match. The daemon still releases an ordinary request after 280 s;
only a shift's request stays. A daemon that stops drops the connection and the prompt is at the terminal, as before.

In the morning the request is still pending as any request is: the page and the apps show its card, the briefing names
it, and "approve billing's push" (`nightshift.release_intent`: an approval word and a shift session's name, while that
session waits) makes billing the active session, which reads its exact request out. Those words approve nothing: the
request had not been read out when they were said. The yes after the read-out, or a tap, answers it through
`_answer_permission` / `/voice/approve`, unchanged. The ledger's entry is then marked "approved by you" or "denied by
you", and a shift that is still on moves that front again.

With `approvals: terminal` in the config, or a launch-mode prompt Pointe cannot hold, the request stays in the
terminal: Blocked with "a permission prompt in its terminal".

"Tell docs to use the old format" is an ordinary send, bound to the user's words as any send is. A send to a session
that has an open question or blocker on the ledger marks it "answered by you", with the words.

## The ledger

`STATE/night-shifts.json` (0600), the last seven shifts. Every text in it passes `readout.mask` first.

```
Shift   {id, at, ends_at, ended, why, how, caps: {hours, messages, followups}, notify, sent,
         fronts: [Front], entries: [Entry]}
Front   {session, session_id, harness, start_id, state: starting|working|waiting|parked|finished,
         tasks: [{text, state: queued|working|done|blocked|parked, followups, sent_at, reported_at}], current}
Entry   {id, kind: done|blocked|decided|asked, session, task, at, text,
         proof, commit, pr,                       # done
         waits_on, request, request_id,           # blocked
         question, choice, otherwise,             # decided / asked
         resolved, resolved_at}                   # "approved by you", "denied by you", "answered by you: ..."
```

In flight is not stored: it is the tasks in state `working`. `Shift.ledger()` gives the four buckets for the screens.
A daemon that restarts picks a running shift up from the file; a report missed meanwhile is caught by the stall rule.

## The morning

`nightshift.morning(shift, now)` builds the report in code, in this order, and `briefing` leads with it:

1. One line: when it ran, tasks done of total, how many blocked, how it ended (complete, the hours, the budget,
   stopped by you).
2. **Decisions made without you**: question, choice, what changes otherwise.
3. **Questions waiting on you**: what a session asked and nobody answered.
4. **Done**, with the proof line; a commit or pull request is on the screen, not spoken.
5. **Blocked**: what each waits on. An approval is named ("billing waits for your approval"), never quoted: a
   briefing's own speech closes the yes window, so a yes after it reads the request out instead of approving.
6. **Still in flight.**

"Brief me on the night" (and the scheduled briefing) puts these parts first when a shift ran since the briefing's
start; sessions that were on the shift are not read a second time, the others follow in the usual order. Each part
reaches the voice as briefing data: it reads, it never sends or approves. The same text is written in the notes and
kept with the briefing.

## Interfaces

- `GET /voice/night-shift`: `{shift, history, caps, limits, pending, sessions}`. `?id=` picks one from the history.
- `POST /voice/night-shift`: `{action: start, items: [{session, task} | {start: {harness, folder, name?}, task}],
  hours?, messages?, notify?}`; `{action: confirm | cancel, id}` for a read-back's card; `{action: stop}`.
  409 while a shift runs, in a meeting, in a challenge; 400 with the reason in `detail`.
- `/voice/status`: `night_shift` (`{on, id, at, ends_at, ended, why, sent, budget, tasks, done, in_flight, blocked,
  decided, asked, fronts: [{session, state, task, done, total}]}`) and `shift_pending` (`{id, line, items,
  expires_in}`).
- The brain's tool `night_shift` (no arguments are trusted), and `briefing` unchanged.
- Prefs: `nightshift.hours`, `nightshift.messages`, `nightshift.notify`.
- All three routes answer the page cookie, the bearer token and the phone key.

## Screens

The same three things on the page, the iPhone app and the Mac app (shared `PointeUI`):

- **Start sheet**: one row per task (a session, or a new session with its agent and folder; the task), the hours, the
  budget, "Alert me about blockers overnight" (off), the rule in one line, Start.
- **Status**: a strip while a shift runs: tasks done of total, sessions, the blocked count, Stop.
- **Ledger**: Decisions, Questions, Done, Blocked, In flight, for the running shift and the last seven.

## Not in this version

Sessions on a node; a shift per session group; interrupting a running turn on Stop; a budget in tokens or money (Pointe
does not see a session's spend); tasks that depend on another session's result; changing a running shift's plan.
