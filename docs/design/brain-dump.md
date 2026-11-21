# Brain dump

Brainstorm, redesigned. You dump your thoughts; Pointe stays quiet and keeps every word; when you say done it structures
them into a prompt, in your own words, and shows it for review; only when you say send does it reach a session.

## What was there, and what was wrong

The old flow ("brainstorm", `state.monologue` in `daemon.py`): a phrase or the dock button started it, `_keep_thought`
collected utterances, and any of about twenty "over" phrases (`guards.over_intent`: "over to you", "what do you think",
"I'm done", "send that to X", a lone "stop" or "wait") ended it by handing **everything** to the voice model as one user
turn (`_end_monologue`). The model then answered, summarised, or called `send_to_claude_code` as it saw fit. The page
and the app showed the last 600 characters of what was said, a "Back to conversation" button, and "Challenge it".

Bugs, each reproduced by a test before the change (the tests now in `tests/test_brain_dump.py` assert the fix):

1. **Tap on, tap off with nothing said still woke the voice.** `/voice/listen {on:false}` pushed
   "[the user thought out loud … (nothing) …]" into the model, which answered to nothing.
2. **The live view was cut to the last 600 characters, mid-word.** `status.monologue.said` was
   `" ".join(thoughts)[-600:]`: the first thoughts fell off the screen while you were still talking, and the view
   started with half a word.
3. **No review step.** The hand-off went straight into the conversation; a rhetorical "What do you think?" or a lone
   "wait" ended the dump and handed the whole thing over. There was nothing to read, fix or discard, and the model
   decided whether and what to send.
4. **The dump lived only in memory.** A daemon restart (a plugin update, `pointe stop`) lost it; the page and the
   app had nothing to show after.
5. **Page and app disagreed.** The app's panel showed the live "hearing" line, the page's did not; the page's hint
   offered "send that to …", a direct send with no review. The dock label flipped to "Back", which said nothing about
   what Back did (it sent).

## The flow

```
conversation ──"brain dump" / button──► dumping ──"done" / Done──► structuring ──► review ──"send it to X" / Send──► sent
                                          │  ▲                                        │  │
                                          │  └────────── "add more" / Add more ───────┘  └── "discard" / Discard ──► gone
                                          └── "discard" / Discard ──► gone
```

- **Enter:** say "brain dump", "just listen", "let me think out loud" (every old phrase still works), or press
  **Brain dump** in the dock (page) or the bottom bar (app). A falling chime; the panel opens.
- **Dumping:** everything you say is a thought. Nothing reaches the voice model or a session. Pointe says nothing,
  session news is held, a permission request is not read out (a soft tone; its card shows, and it is put to you at
  review). Pauses of any length are fine. The panel lists each thought as it lands, with the live "hearing" line under
  it, on both surfaces.
- **Done:** say "done", "over to you", "what do you think", "structure it", or press **Done**. Nothing said: back to
  the conversation, no model turn (bug 1). Otherwise the reading model structures the thoughts (one JSON call, ~2 s,
  `braindump.structure`): **Goal**, **Context**, **Constraints**, **Open questions**, each item in your own words. A
  guard in code drops any item whose words are not mostly yours (`braindump.invented`), and when the model fails or is
  unavailable the prompt is your raw thoughts under Context, still editable and sendable. Held session news and a
  pending approval follow the review line.
- **Review:** the structured prompt, editable as one text: a heading line per section that has something (Goal,
  Context, Constraints, Open questions), the goal as a line, the rest as `- ` bullets, a blank line between; empty
  sections are left out. No machine framing in it: "in their own words, nothing added" is in the header `_send_dump`
  puts above the text at send time (`braindump.sent_header`), so the user never edits it. Under the text, a **To:**
  field (a field, not a button): **Orchestrator** first, then the sessions, preselected by where the user was when the
  dump started (see "Where Send goes"), then **Send**, the one primary action (two clicks:
  the first arms it, reading "Tap again to send" with a ring, for four seconds). Below, quiet outlined **Add more** (back
  to dumping; the next Done folds the new thoughts into the existing prompt), **Read it back**, **Challenge it**; then
  **Discard** apart, in red (two clicks). Page and app have the same words and the same order. Pointe says one line: "Your brain dump is structured: send it, add more, or
  discard." In review, speech that is not one of those commands is ordinary conversation; the card stays until you act.
  "Read it back" has Pointe read the prompt aloud.
- **Send:** the reviewed text goes to the named session **verbatim**, through `deliver`, with the same bookkeeping as a
  spoken send (`state.sent`, the Recent requests panel, the thread, the brief refresh). The voice model is told in one
  line and says so; it never rewrites the prompt. The checks that are rules, not judgment, still apply: not during a
  meeting, never a relay of an approval the session takes only typed, and a prompt that touches production credentials
  is refused once with the risk stated (a second Send goes), as in `_send_now`. A spoken "send it to X" while still
  dumping structures first and preselects X; the send itself waits for "send" or the button, so what goes is what was
  shown.

### Where Send goes

The user dumps from wherever they were: pinned to one session, or talking to the orchestrator. Send defaults back to
there. `_start_dump` keeps the routing (`braindump.capture`: the mode, and in session mode the pinned session's id and
name) in the dump's `route`, saved with it in `brain_dump.json`; "add more" keeps it. `braindump.send_to` turns it into
the default, against the sessions there are at review time: a target named by voice while dumping ("send that to X",
"send that to the orchestrator") wins; else session mode gives the pinned session (by id, so a rename keeps it; else by
name, so a session that came back under a new id keeps it), and orchestrator mode the orchestrator. A pinned session
that is gone falls back to the orchestrator, and `gone` carries its name for the sheet to say so. A dump saved before
`route` existed follows the routing at review time. Status carries the result as `brain_dump.send_to`; the page and the
app preselect it, list **Orchestrator** first, and keep the user's own pick.

Sending to the orchestrator does not deliver anything itself: `_dump_to_orchestrator` clears the dump and hands the
text to `_user_text`, the path words typed in the app take, as the user's turn ("My brain dump, structured:" above it,
`braindump.orchestrator_turn`). The voice model answers it or calls `send_to_claude_code`, and every check there
applies (fresh speech, relevance, production credentials). It needs a call and no meeting (409). The voice model is
told first, without a reply, that the user read the text and pressed Send (`braindump.reviewed_line`), and a reply to
that turn that asks "send it?" is sent back to it (`daemon._dump_reply_problem`): on live calls about one reviewed dump
in three was answered with "Send it?". In session mode, that one turn is routed as in orchestrator mode:
`state.orchestrated_turn` holds the turn's text, and `_routing_mode()` answers "orchestrator" while it is still
`last_utterance`, for `_route`, `_brain_named` and the pinned-session refusals; the voice model is told so first,
without a reply (`braindump.orchestrated_line`). `REGISTRY.mode` never changes, and the user's next words replace
`last_utterance`, so the turn after is pinned again.

### Interruptions

| Event | What happens |
|---|---|
| A permission request arrives while dumping | Not read out (soft tone); the card shows; a spoken yes approves nothing (`permission_delivered_at = inf`, as before); it is asked at review |
| You switch sessions while dumping | Allowed; the dump is not tied to a session until Send |
| The call drops, the phone locks, the tab closes | The dump stays in the daemon (`STATE_DIR/brain_dump.json`). On the next call, the panel shows it and Pointe says: "Your brain dump from earlier is still here, N thoughts: keep going, say done, or discard." Dumping stays on until you act |
| The daemon restarts | Same: the file is loaded at start; a dump in review comes back in review |
| A meeting starts | As before: the thoughts become the meeting's brief, and the dump ends |
| "Challenge it" | As before: the thoughts become the plan, the dump ends |
| Drive mode | Works by voice alone: the review line is spoken; "send it to X" sends |
| Push to talk | Thoughts arrive per press, as any speech |

### Compatibility

- `/voice/listen {on}` stays: on = start, off = done. `status.monologue` stays while dumping (`{since, said}`) for an
  older app. `modes.BRAINSTORM` is an alias of `modes.BRAIN_DUMP` (`mode_state.mode` = `brain-dump`).
- Every old voice phrase (`guards.listen_intent`, `guards.over_intent`) still works and means the same, minus the
  send: "send that to X" during a dump now structures and preselects X.

## API

| | |
|---|---|
| `POST /voice/dump` | `{action: start \| done \| more \| edit \| discard \| send \| read, text?, session?, to?}` → `{brain_dump}`. Send: `session`, or `to: "orchestrator"`, or neither for `send_to`. 400 on a bad action or an edit with no text; 409 with the reason: no call, a meeting on, nothing to send, no such session, offline, a meeting on at send time, credentials (once). Page cookie, bearer token, phone key |
| `POST /voice/listen` | `{on}`: alias of start / done |
| status `brain_dump` | `null`, or `{id, state: dumping \| structuring \| review, since, thoughts: [{text, at}], prompt: {goal, context: [], constraints: [], open_questions: [], text} \| null, target, problem, resumed, dropped, route, send_to: {orchestrator, session, gone}}` |
| status `monologue` | while dumping, `{since, said}` (compat) |
| status `mode_state.mode` | `brain-dump` while dumping |

## Where it lives

- `braindump.py`: phrases (start, done, review commands), the `Dump` record, the structuring prompt and parser, the
  invention guard, the prompt text, the file. Rules in code, each with a test.
- `daemon.py`: `_start_dump`, `_keep_thought`, `_finish_dump` (structure → review), `_send_dump`, the route, the
  status field, the reconnect line. `modes.BRAIN_DUMP` holds news, no nudges, no read-outs, no speech.
- `ui.html`: the `#dump` panel (thoughts, hearing, Done / Discard), the `#dump-review` sheet (sections as editable text,
  session picker, Send / Add more / Discard), `DUMP_COPY`. The dock button `#listen` reads "Brain dump" / "Done".
- `apple/PointeKit/Sources/PointeUI/BrainDump.swift`: `API.BrainDump`, `BrainDumpCopy` (word for word the page's), `BrainDumpPanel`,
  `BrainDumpReview`. `CallView` shows them; `BottomBar` labels the button.
- Docs: `docs/features/brain-dump.md`; README table.

## Also in this change

The web page loses its **Drive** dock button: drive mode is for a phone in a car, and a laptop page offering it made no
sense. The `#drivebar` banner stays, shown only while drive mode is on (the phone turned it on), with "I've stopped" so
the laptop can still explain the short answers and end it. The daemon's `/voice/drive`, the voice phrase and the app's
Drive control are unchanged.

## Tests

- `tests/test_brain_dump.py`: phrases and aliases; the record (cap, status); structuring (parse, invention guard,
  fallback, add-more folding); the file (save, load at start, cleared on discard and send); the daemon: nothing reaches
  the model while dumping, Done with nothing said is silent, Done structures and reads the review line, held news and a
  pending approval follow, Send delivers verbatim and records, Send refusals (meeting, typed approval, credentials once),
  Discard, Add more, the reconnect line, meeting and challenge take the thoughts, the listen alias and the `monologue`
  mirror, the page and the app share their copy; where Send goes: the routing captured at start and kept through add
  more and on disk, the default in both modes, the picker and the voice overriding it both ways, "send it to the
  orchestrator" in English and Hebrew, the gone-session fallback (rename and return by name kept), the orchestrator send
  needing a call and no meeting, a 1.6 file without `route` following the routing now, and in session mode the dump's
  turn reaching another session while the next turn is pinned again.
- `tests/test_ui_page.py`: ids; the drive button gone from the dock and the More sheet; `tests/test_brain_dump_page.py`:
  the panel and the review sheet rendered against the stub Mac (`tests/page_rig.py`), clicks post the right actions; the
  To: picker lists Orchestrator first, preselects `send_to`, keeps the user's pick across a redraw, and says when the
  pinned session is gone.
- `tests/e2e/page_brain_dump.py`: live: a stand-in phone dumps three thoughts, says done; the page shows the review;
  the To: picker defaults to Orchestrator (orchestrator mode); Send to a registered fake session delivers the exact
  text; a second dump sent to the orchestrator becomes the user's turn and the voice answers it; Discard. `tests/e2e/page_drive.py`: drive mode via
  `POST /voice/drive`, the banner shows, no `#drivebtn`.
- iOS: `BrainDumpTests` (decoding, copy parity, state, the To: default in both modes, override, gone, an older Mac),
  `BrainDumpUITests` on `-demo brainDump` / `brainDumpReview` / `brainDumpPinned` / `brainDumpGone`.
