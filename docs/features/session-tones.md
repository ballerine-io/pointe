# Session tones

With five sessions on the voice you wait for the name to know who is reporting. With session tones on, a short tone
plays first, and it is the same tone for that session every time: the sound says who before the first word.

Off unless you turn it on. The tones and their measure are `pointe/tones.py`; the daemon plays one ahead of a
background session's report (`daemon._session_tone`).

## Use it

| Surface | Where |
|---|---|
| The page | Settings → Turn taking → Session tones |
| iPhone | Settings (•••) → Session tones |
| Mac | Settings → Session tones |

It is one setting on the Mac. No phrase switches it.

## What you hear, and when

- Before the report of a session that is not the one you are talking to: in orchestrator mode, any session that
  finishes a turn and has something for you. The session you are focused on, or whose answer you are waiting for,
  gets no tone: its words are the reply.
- One tone, under a third of a second, at about an eighth of full scale (the waiting sound is a tenth, the chimes a
  quarter). It is a plain sound in the call's own output, in order with the voice, so nothing that times Pointe's
  speech takes it for speech.
- Never while Pointe is muted (drive mode holds mute, so it plays on the road), in whisper mode, in a meeting, or over
  anyone who is talking.
- A session gets its tone at its first report and keeps it, across restarts of Pointe. It starts from a hash of the
  session's name and moves to the next free tone when another session on the voice has that one, so sessions do not
  share a tone until there are more than eight.
- On the screen: a session's row names its tone beside its agent ("Codex · tone: rise"), on the page and in both
  apps, while the setting is on.

## The eight tones

Each is one to three notes of the same soft sine with its octave: rise (392 Hz 523 Hz), fall (1319 Hz 880 Hz), double (659 Hz rest 659 Hz), long (262 Hz), leap (440 Hz 880 Hz rest 1319 Hz), triple (1568 Hz rest 1568 Hz rest 1568 Hz), dip (1175 Hz 392 Hz 1175 Hz), late (rest 587 Hz rest 1046 Hz). They differ in pitch, in contour and in
rhythm, never in loudness.

## Distinct, by measure

The distance between two tones is one minus the cosine likeness of their third-octave spectra, taken every 30 ms over
the same third of a second: 0 for the same sound at any loudness, 1 for two sounds with no energy in the same band at
the same moment. A third of an octave is about what the ear resolves as one band, so a tone moved by a semitone
measures as nearly the same tone (the test checks that it does). No two tones may be closer than
0.50, and no tone may be that close to another sound Pointe makes (the waiting sound, the two-note
chime). `python3 -I pointe/tones.py` prints this table; `tests/test_tones.py` fails when it and the code differ.

| | rise | fall | double | long | leap | triple | dip | late |
|---|---|---|---|---|---|---|---|---|
| rise |  | 0.97 | 0.81 | 0.77 | 0.70 | 1.00 | 0.72 | 0.64 |
| fall | 0.97 |  | 0.91 | 1.00 | 0.88 | 0.63 | 0.90 | 0.93 |
| double | 0.81 | 0.91 |  | 0.92 | 0.99 | 0.83 | 0.93 | 0.84 |
| long | 0.77 | 1.00 | 0.92 |  | 0.95 | 1.00 | 0.94 | 0.93 |
| leap | 0.70 | 0.88 | 0.99 | 0.95 |  | 0.72 | 0.92 | 0.97 |
| triple | 1.00 | 0.63 | 0.83 | 1.00 | 0.72 |  | 1.00 | 1.00 |
| dip | 0.72 | 0.90 | 0.93 | 0.94 | 0.92 | 1.00 |  | 0.66 |
| late | 0.64 | 0.93 | 0.84 | 0.93 | 0.97 | 1.00 | 0.66 |  |

The closest two are fall and triple, 0.63 apart; the threshold is 0.50.

**What this does not show.** The measure is a necessary check: it rules out two tones that are the same sound. It does
not show that a person can name the session from the tone. The acceptance for that is a listening test (ten people,
five minutes of use, the session named from the tone alone above 80% of the time), and that test is still owed. Until
it is run the feature stays off by default, and nothing here says the tones are told apart by ear.

## Not built

- No way to hear a session's tone on demand, or to choose it.
- No second voice for reports.
- The tone is not played on a notification when no call is up.

## The tests

| What | Where |
|---|---|
| Eight tones, short and quiet; no two closer than the threshold, and none close to another sound of Pointe's; the measure tells same from different; a session keeps its tone; off by default; a background report starts with the tone and the focused session's does not; nothing while muted | `tests/test_tones.py` |
| The page: the setting, and a row names its tone | `tests/test_tones_page.py` |
| The apps: the setting and the row's words | `apps/PointeKit/Tests/PointeUIUnitTests/TonesTests.swift` |
