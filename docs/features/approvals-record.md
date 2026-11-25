# Approvals record

Every answer to a permission request that went through Pointe is kept, and you can read it: when it was answered,
whether by voice or by a tap, the exact request, and for a spoken answer the voice lock's score of the voice that said
it. A spoken "yes" leaves no click behind; this is where it leaves a line.

The rules live in `pointe/approvals.py`; the daemon writes one line per answer (`daemon._apply_answer`) and serves the
record at `GET /voice/approvals`, behind the same lock as every other route.

## Use it

| Surface | Where |
|---|---|
| The page | Settings → Approvals record |
| iPhone | Settings (•••) → Approvals record |
| Mac | Settings → Approvals record |

It is read only: nothing in it answers a request. There is no phrase for it; ask Pointe "where is the approvals
record" and it tells you the path.

## What a row says

| Part | Example | Notes |
|---|---|---|
| The answer and how | Approved by voice · Denied by a tap · Approved from a notification | "by a tap" is the card on the page, the iPhone or the Mac; "from a notification" is the action on an alert ([Alerts](alerts.md)) |
| When | 20 Nov, 09:14 | the Mac's own clock |
| The session | bluebell/dev · devbox | with its machine when it is not this Mac |
| The request | `Bash` then `git push --force-with-lease origin retry-fix` | word for word what the card showed: the tool, then its input. Secret-looking values are masked, as everywhere in the journal. Over 4,000 characters it is cut, and the row says so |
| The voice lock | Voice lock approvals: score 0.71 | only for a spoken answer. "The voice was not scored" when the lock could not tell (too short, no voiceprint for this device); "Voice lock off" when the lock was off. A tap has no voice, so no line |

The score is the one the [voice lock](voice-lock.md) took its decision on: the likeness of the voice to your
voiceprint, from 0 to 1. A spoken yes that the lock refused approved nothing, so it is not in the record.

## What it holds, and for how long

- An answer that reached the session: approved or denied, by voice, by a tap, by a notification's action. An answer
  that did not arrive ("the answer did not reach billing") is not a row.
- Not an answer given in the session's own terminal: that never went through Pointe.
- The record is the daemon's journal (`~/.claude-voice/journal.jsonl` and the one older file it rotates to at 20 MB),
  read back each time you open it. Nothing else is stored. It is as old as the journal is long, it shows the newest
  200, and deleting the journal empties it. The journal never leaves the Mac; the iPhone reads the record over the
  paired link.
- A request answered before this version has no row: the journal then held only the session's name and the answer.

## The tests

| What | Where |
|---|---|
| Every approval in a fixture journal is in the record, newest first; a tap and a spoken yes are written with the exact request and the score; a lost answer is not; the endpoint is locked like the rest | `tests/test_approvals.py` |
| The page: every approval is a row, each says when, how, the request and the score | `tests/test_approvals_page.py` |
| The apps decode what the daemon sends for the same journal; a row's words | `apps/PointeKit/Tests/PointeUIUnitTests/ApprovalsTests.swift` |
| iPhone: Settings opens it, every approval is a row, VoiceOver reads the whole row | `apps/ios/PointeUITests/ApprovalsUITests.swift` |
| Mac: the same, through the Accessibility API | `apps/macos/e2e/smoke.py` |
