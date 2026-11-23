# Challenge me (devil's advocate)

After a [brain dump](brain-dump.md), say "challenge this": the voice argues against your plan, one objection at a time, grounded in
what it knows about your sessions, until you end it. It can look things up; it can never send.

The rules live in `challenge.py` (start and end phrases, the plan, the evidence, the opening, the per-step line, the
verdict); `daemon.py` starts, ends and records it.

## Use it

- **Start:** "challenge this", "challenge me", "play devil's advocate", "poke holes in this", "תתקוף את זה", "תאתגר
  אותי". During a brain dump, "challenge this" ends the dump and challenges what you said; in its review, the structured
  prompt is the plan.
- **End:** "you've made your point", "verdict", "back to normal", "end challenge", "stop", "די", "חזרה לרגיל". The voice
  then gives a verdict: the weakest point and the fix.
- Each phrase must be a whole utterance, spoken or typed. It is caught in code before the permission check, never
  reaches the voice model as a turn, and never approves.
- **Page:** a Challenge button in the dock ("End challenge" while on), "Challenge it" in the brain dump's review, and a
  Challenge panel with the plan, then Objection / You / Verdict in order.
- **iPhone app:** Settings (••• at the top) → Challenge ("End challenge" while on), or "Challenge it" in the brain
  dump's review. The Challenge panel shows the plan and the exchange.
- **Mac app:** the iPhone app's screens: Settings (••• at the top, or ⌘,) → Challenge, or "Challenge it" in the brain
  dump's review.
- In the apps, Settings → Challenge can be chosen only with a call up, and not in a meeting, while you dump thoughts, or
  in drive mode.

## What grounds it

The opening carries the plan (the brain dump, else your last six sentences within 15 minutes) and numbered evidence
`[E1]…`: the active session's notes (decided, ruled out, where it stands, open questions, goal), its last 12 record
lines, and diffs against `HEAD` of files it edited that were recently shown on screen, plus up to three sessions the
plan names. Everything passes the credential mask. With no evidence, it says so and argues from the plan only, and it
answers "I don't know" to a question of fact. After six objections it asks for your verdict.

## What it may do, in code

- Tools: speak, list sessions, and ask a session a side question. Everything else is refused, including sends and
  briefings. A send is refused with "Not sent: you are in a challenge; end it first, then say what to send."
- Ending it resets the send window, so neither the end words nor a "fine, do it" said during the challenge can
  authorize a send afterwards.
- Session reports and idle nudges wait for the end. Side-question answers and permission read-outs do not: a permission
  is read out and answered as in conversation, and an objection spoken after the read-out closes its yes window.
- A spoken end phrase that is a no ("stop", "עצור") also denies a pending request, under the rules that bind any no,
  before the challenge ends. "You've made your point", "enough" and "די" only end it.
- Not in a meeting (409). A meeting that starts ends it with no verdict, and so does the end of the call. Driving ends
  it too: see [drive mode](drive-mode.md).
- It needs the default text-model front: a realtime front cannot be kept from acting (409). With
  `CLAUDE_VOICE_EARS=native` the phrases are not caught; taps and typed words work.

## Measured

[`bench/results/challenge.md`](../../bench/results/challenge.md): six cases, five repeats each, before and after the
challenge's brackets. `claude-sonnet-5-5` (the default brain) went from 15/30 to 30/30, `gemini-3.8-flash` from 21/30
to 30/30. The system prompt and tool schemas are unchanged.

## API

| | |
|---|---|
| `POST /voice/challenge` | `{action: start\|end}` → `{challenge}`. 400 on a bad action; 409 with the reason: no call, a meeting on, already on, none on, a realtime front, driving. Page cookie, bearer token, phone key |
| status `challenge` | `null`, or `{id, on, since, ended_at, plan, sessions, objections, verdict, evidence, items: [{kind: objection\|rebuttal\|verdict, text, at}]}`. The last one stays (`on: false`) until a new one starts |
| status `mode_state.mode` | `challenge` while on |
| notes | kinds `objection`, `rebuttal`, `verdict` |
