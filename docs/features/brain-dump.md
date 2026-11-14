# Brain dump

Dump your thoughts; Pointe stays quiet and keeps every word. Say done, and it structures them into a prompt in your own
words (goal, context, constraints, open questions) for you to review. Only when you say send does it reach a session.
This replaces "brainstorm"; every old phrase still works.

The rules live in `braindump.py` (what starts and ends it, the review commands, the record, structuring and its guard,
the file); `daemon.py` runs it. Design and the bugs it fixed: [docs/design/brain-dump.md](../design/brain-dump.md).

## Use it

- **Start:** "brain dump", "let me dump my thoughts", "just listen", "let me think out loud", "רק תקשיב"; or the
  **Brain dump** button (the page's dock, the app's bottom bar). A falling chime; the panel opens.
- **Dump:** talk. Every thought lands on the panel as it is heard, with the live line under it. Pauses of any length are
  fine. Pointe says nothing, session news waits, a permission request is not read out (a soft tone; its card shows).
- **Done:** "done", "over to you", "what do you think", "structure it", "סיימתי"; or **Done**. Nothing said: back to
  the conversation, silently. Otherwise a rising chime, and in a few seconds the review. "Discard", "forget it",
  "never mind" (the whole utterance), or **Discard**, ends it with nothing kept.
- **Review:** the structured prompt, editable, as plain sections (Goal, Context, Constraints, Open questions; empty ones
  left out) with bullets; a **To:** field (the active session preselected); **Send** (two clicks: the first reads "Tap
  again to send"), **Add more** (keep dumping; the next Done folds the new thoughts in), **Read it back**,
  **Challenge it** ([devil's advocate](challenge.md) on the prompt), **Discard** (two clicks). By voice: "send it to X",
  "send it" (the preselected session), "add more", "read it back", "discard". Anything else you say is ordinary
  conversation; the card waits.
- **Send:** the text as shown goes to the session word for word, headed `[from the user, by voice: their brain dump for
  X, in their own words, structured; nothing added]`. Pointe says it went. It shows in Recent requests like a spoken send.

## What holds, in code

- Nothing said while dumping reaches the voice model or a session. Done tells the model one line ("ready to review");
  the thoughts themselves never go to it unless you say "read it back".
- The prompt is your words: an item whose words are not mostly yours is dropped (`braindump.invented`, tested); when the
  model fails or has no key, the prompt is your thoughts under Context, still editable and sendable (the review says so).
  Credentials in a thought are masked as everywhere else.
- A spoken "send it to X" while still dumping structures and preselects X; the send waits for "send" or the button, so
  what goes is what was shown.
- The send still refuses what a spoken send refuses by rule: during a meeting (409), a relay of an approval the session
  takes only typed (409), and a prompt touching production credentials once, with the risk stated (a second Send goes).
- A yes said while dumping approves nothing (the pending request is asked again at the review). Session news held
  during the dump is told after the review line.
- The dump is written to `~/.claude-voice/brain_dump.json` on every change. A dropped call, a locked phone, a closed tab
  or a daemon restart loses nothing: on the next call the panel shows it and Pointe says it is still here (keep going,
  say done, or discard).
- A meeting that starts takes the thoughts as its brief; "challenge this" takes them as the plan. Both end the dump.
- Not in a meeting (409). Works in drive mode by voice alone.

## API

| | |
|---|---|
| `POST /voice/dump` | `{action: start \| done \| more \| edit \| discard \| send \| read, text?, session?}` → `{brain_dump, sent_to?}`. 400 on a bad action or an edit without text; 409 with the reason: no call, a meeting on, a dump already in review, nothing to send, no such session, offline, credentials (once). Page cookie, bearer token, phone key |
| `POST /voice/listen` | `{on}`: the old switch; on = start, off = done |
| status `brain_dump` | `null`, or `{id, state: dumping \| structuring \| review, since, thoughts: [{text, at}], dropped, prompt: {goal, context, constraints, open_questions, text} \| null, target, problem, resumed, fallback}` |
| status `monologue` | while dumping, `{since, said}`: the old field, for an older app |
| status `mode_state.mode` | `brain-dump` while dumping |
