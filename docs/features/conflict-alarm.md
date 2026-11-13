# Conflict alarm

One session reports "the migration passed"; twelve minutes later another reports "the test using the new column
failed". Pointe says so at once, with both claims, and offers to put a question to either session. It never asks a
session on its own.

It works for sessions of every harness. The rules live in `conflicts.py`; the daemon starts a check after each session
report and delivers what it accepts.

## Use it

- The voice says it, and a card shows the two claims with Ask (either side) and Dismiss. One card at a time, the
  newest, with "N more disagreements" under it. The app plays a warning haptic when a card appears.
- **Ask** sends your typed words `Send <name> this question: <question>` through the normal path, so every send gate
  applies, and typed words can never approve.
- **Dismiss** (a tap, or "I know" / "later" within 5 minutes of the spoken alarm) keeps that pair quiet for the rest of
  the call.
- Settings: `conflicts.on` (default on; off means no check at all) and `conflicts.spoken` (default on; off is "Card
  only").

## What is checked, in code

- **Pairs.** Another registered session whose last report is under 4 hours old, and that shares a git root or folder,
  or shares two or more names and edited files with this one, or is named in its new message. Only edits count as
  touching a file; reads never do, and common names (`index`, `main`, `README`, …) are ignored.
- **Accepted only if** the reading model says the claims conflict and are still current; each claim's outcome words
  and numbers appear in its own session's message (and at least half its content words); and the two claims do not say
  the same thing.
- **Limits.** One alarm per pair per 30 minutes, the same claims never twice. Sessions on different branches are never
  urgent.
- **Speech.** An urgent conflict jumps the queue; a normal one waits its turn. It waits while a push-to-talk press is
  open and while a read-out's yes window is open, so it never takes a yes away from a request or talks over you. It
  never touches a permission. During a meeting it is never spoken, not even after: the card and the note stay.
- **Secrets.** The reading model's input and every field of an accepted conflict pass the credential mask, so status,
  notes, the phone and the voice never carry a session's credential.
- **Reading model down:** no alarm, and a journal line `conflict check skipped: ...`.

## Alerts

Each open conflict is an attention item titled "Two sessions disagree", with the two session names only (the claims
quote the sessions' messages and stay in the app and the page). It reaches iPhone notifications, mirrored to the watch
with no actions, and the page's desktop alerts. See [alerts](alerts.md).

## Limits

Offline tests cover mixed harnesses on each adapter's real record format. There is no live end-to-end run with real
OpenCode or Codex sessions, and no measured precision.

## API

`POST /voice/conflicts` (page cookie, bearer token, phone key):

| Body | Does | Errors |
|---|---|---|
| `{action: "dismiss", id}` | closes the card and its note; the pair stays quiet for the call | 404 unknown or closed id |
| `{action: "ask", id, side: "a"\|"b"}` | sends the typed question through the normal send path | 400 bad side; 404; 409 no call, or a meeting on |

Status `conflicts: [{id, a, b, agent_a, agent_b, claim_a, claim_b, at_a, at_b, at, why, severity: high|normal,
questions: {a, b}, branches: {a, b}|null, asked, state}]`, open ones only; `a` is the earlier report. Notes get kind
`conflict`. Prefs `conflicts.on`, `conflicts.spoken` in `GET/POST /voice/prefs`.
