# Voice evals

`sim.py` is a voice call without audio: the real daemon code and the real voice model, driven by text. A tester
plays both the user and Claude Code, so a whole conversation can run in minutes with nothing touching a live call.
Audio, speech recognition and barge-in timing are not covered here; `tests/e2e` covers those.

`scenarios/*.json` are synthetic sessions (invented companies, names and paths only), each with a `.md` script.
Never put real session content here. Each run calls the paid Gemini API, at a small cost.

Score a run from 1 to 5 on: knows the session, report focus, moves the work forward, accuracy, spoken quality.
