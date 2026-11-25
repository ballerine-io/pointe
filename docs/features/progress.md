# Progress updates

After "Asking billing" there was silence until the answer, and a long silence reads as a dead call. With progress
updates on, Pointe says one short line while a session works on your request: the first about 20 seconds in, then one
every 45 seconds, until the session answers.

> Billing is still working, 20 seconds in. Latest step: running the tests.

Off by default. The rules live in `pointe/progress.py`; the daemon says the lines in `daemon._progress_tick`.

## Use it

- **Voice:** "keep me posted" turns it on, "stop updates" turns it off. Also "keep me updated", "give me progress
  updates", "no more updates", "תעדכן אותי", "בלי עדכונים". Each must be a whole short utterance: "keep me posted on what
  billing decides" is a request for the session, and "stop updates" with the updates off is a sentence like any other.
- **The page:** Settings → Turn taking → Progress updates.
- **The iPhone and the Mac:** Settings (•••) → While you wait → Progress updates.

The setting lives on the Mac (`progress.spoken`), so every screen shows the same.

## Every word is from the session's record

No model writes these lines. Each has two facts, both read from the session:

- **How long:** since your request reached the session, rounded down ("20 seconds", "a minute and a half").
- **Its latest step:** the newest tool the session used since your request, named in fixed words from the tool and its
  input: "running the tests" (the command itself is a test run), "running a command", "editing pricing.py", "reading
  README.md", "searching the code", "searching the web", "reading a web page", "running a helper agent", "updating its
  task list", "using a tool".

A command is never said, and of a path only the file's name. The session model's own description of a step is never
used: "run the tests" written over `cat build.log` is said as "running a command". With no step since your request the
line names none ("Billing is still working, 20 seconds in."); with the same step as the last update it says so
("Billing is still on the same step, a minute in: running the tests."). A session on another machine reports no steps
to this Mac, so its lines say how long and no step.

## When nothing is said

- **After the answer.** When the session's turn ends the updates end; its answer follows by the usual rules. A line
  that waited for a quiet moment is dropped if the session finished meanwhile, never said late.
- **While the session waits on you.** A request to approve is read out by its own rules; "still working" would be false.
- **Over anyone.** A line waits until you are not mid-sentence and Pointe is not answering, like other news.
- **In a meeting, a hold, a brain dump, a challenge or a briefing.**
- **After a switch.** Moving to another session or to the other mode ends the updates on what you left, as it
  [stops speech](skip.md#a-switch-drops-what-waited). The answer itself still arrives.
- **After the call ends,** and for a night shift's own messages, which are not your request.

**Muted,** the line is text in the conversation like every other line, and the status says Writing….
**In drive mode** it is spoken: it is under 25 words and names no screen.

## On the screen, always

Whether or not the lines are spoken, the status line says "billing is working…" while a session has your request
([Thinking](thinking.md#what-the-status-line-says)).

## The wire

| Call | Answer |
|---|---|
| `POST /voice/prefs {"progress.spoken": true}` | the setting, on |
| `GET /voice/status` → `phase` | `{"name": "working", "session": "billing", "since": …}` while a session has the request |
