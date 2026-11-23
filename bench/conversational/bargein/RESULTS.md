# bargein: Barge-in and Time to a Correct Answer (synthetic speech), v0.1

A reproducible self-evaluation on synthetic speech, not a leaderboard. One system under test (Pointe) and reference arms written by the same team. Every number below is computed by `run.py report` from the committed rows.

Runs: bargein-20261123-040244. Dates: 2026-11-23 to 2026-11-23. Agent: `claude-haiku-5-5` in Claude Code 2.1.330, `--permission-mode acceptEdits`, one worker. Pointe commit `7113efa273cb`, setup (default) (brain=anthropic:claude-sonnet-5-5, reader=anthropic:claude-sonnet-5-5, checker=gemini:gemini-3.5-flash-lite, ears=soniox, mouth=elevenlabs:eleven_v4_turbo, notes=[]). Spend: $2.93 in these rows; $3.41 for bargein in the ledger with adapter debugging and preflight probes, of a $14.00 cap (computed from token usage and list prices, not metered).

## Part A: stopping a working agent (synthetic speech, 24 items, one Kokoro voice each)

| Arm | Halt (stop, undo, redirect) | Missed stop | False stop on backchannels | Overshoot, files (median / p90) | Time to halt, stop items (median / p90) | Redirect | Undo | Stayed stopped (stop, undo) | Setup failed / errors / capped | Load-flagged |
|---|---|---|---|---|---|---|---|---|---|---|
| pointe | 0/18 (upper bound 18%) | 18/18 = 100% [82%, 100%] | 0/6 (upper bound 39%) | n/a (0 censored) | n/a (8 censored) | 0/6 (upper bound 39%) (left 0, moved 0) | 0/4 (upper bound 49%) | 0/12 (upper bound 24%) | 0 / 0 / 0 | 5 of 24 |
| llm-router | 18/18 = 100% [82%, 100%] | 0/18 (upper bound 18%) | 0/6 (upper bound 39%) | 1.50 / 2.00 (0 censored of 18) | 3.19 s / 4.84 s (0 censored of 8) | 0/6 (upper bound 39%) (left 0, moved 0) | 2/4 = 50% [15%, 85%] | 12/12 = 100% [76%, 100%] | 0 / 0 / 0 | 5 of 24 |
| naive | 11/18 = 61% [39%, 80%] | 7/18 = 39% [20%, 61%] | 0/6 (upper bound 39%) | 0.00 / 1.00 (0 censored of 11) | 1.27 s / 2.62 s (1 censored of 8) | 0/6 (upper bound 39%) (left 0, moved 0) | 0/4 (upper bound 49%) | 11/12 = 92% [65%, 99%] | 0 / 0 / 0 | 5 of 24 |
| keyboard | 18/18 = 100% [82%, 100%] | 0/18 (upper bound 18%) | 0/6 (upper bound 39%) | 0.00 / 0.00 (0 censored of 18) | 0.00 s / 0.00 s (0 censored of 8) | 0/6 (upper bound 39%) (left 0, moved 0) | 4/4 = 100% [51%, 100%] | 12/12 = 100% [76%, 100%] | 0 / 0 / 1 | 2 of 24 |
| null | 0/5 (upper bound 43%) | 5/5 = 100% [57%, 100%] | 0/3 (upper bound 56%) | n/a (0 censored) | n/a (2 censored) | 0/1 (upper bound 79%) (left 0, moved 0) | 0/2 (upper bound 66%) | 0/4 (upper bound 49%) | 0 / 0 / 0 | 3 of 8 |

`null` ran on a seeded 8 items: the job runs to its end by construction and each run still costs an agent session, so the floor is confirmed on a sample. Halt means the job that was running when the user spoke stopped before `step_20.txt` (its files come every 2 s; a file after a gap of more than 4 s belongs to a later run the agent started); stayed stopped means no later run wrote step files in the repo root either. Time to halt is the last root step file's time after the end of the user's speech (or the keypress), at the job's 2 s resolution. Overshoot is files written after that point minus one file in flight. A redirect counts when the job stopped, `out/` ends with steps 04 to 20, and steps 01 to 03 are either left in place or moved to `out/` (both accepted).

## Part B: time to the first correct answer (synthetic speech, 30 questions, one Kokoro voice each)

| Arm | Correct within 45 s | First audio (median / p90) | Time to correct answer (median / p90, censored) | Correct within 10 s | Correct within 30 s | Clarifications | Load-flagged |
|---|---|---|---|---|---|---|---|
| pointe | 19/30 = 63% [46%, 78%] | 4.38 s / 6.68 s (1 censored of 30) | 27.28 s / 37.70 s (11 censored of 30) | 1/30 = 3% [1%, 17%] | 13/30 = 43% [27%, 61%] | 3 | 6 of 30 |
| llm-router | 28/30 = 93% [79%, 98%] | 5.75 s / 8.26 s (0 censored of 30) | 10.41 s / 14.57 s (2 censored of 30) | 13/30 = 43% [27%, 61%] | 27/30 = 90% [74%, 97%] | 0 | 2 of 30 |
| naive | 28/30 = 93% [79%, 98%] | 4.06 s / 6.68 s (0 censored of 30) | 9.73 s / 14.24 s (2 censored of 30) | 16/30 = 53% [36%, 70%] | 26/30 = 87% [70%, 95%] | 0 | 3 of 30 |
| keyboard (time to correct text, not comparable with spoken times) | 30/30 = 100% [89%, 100%] | n/a (text) | 1.16 s / 3.09 s (0 censored of 30) | 28/30 = 93% [79%, 98%] | 30/30 = 100% [89%, 100%] | 0 | 1 of 30 |

Times run from the end of the user's speech (keyboard: the Enter key) on the runner's monotonic clock. Spoken answers are scored on the recorded audio through the one pinned Whisper large-v3-turbo, the same for every arm; an item never answered correctly within 45 s is censored and counted beside each median. When an arm asks a question back, the scripted user answers it once (a clarification, not a penalty) and the clock keeps running from the first question.

## Pointe against llm-router, paired by item (synthetic speech)

- Part A success (halt, undo, redirect; no false stop): Pointe 6/24, llm-router 16/24, difference -42% [95% bootstrap over items -62%, -21%].
- Part B correct answer: Pointe 19/30, llm-router 28/30, difference -30% [95% bootstrap over items -47%, -13%].

## What the raw logs show (counted by `run.py report` from events.jsonl)

- Pointe, Part A stop, undo and redirect runs (repeats included): in 21 of 27 the daemon log shows the spoken request sent to the session as a message (`-> kiln:`), and in 21 of those the job still ran to its end. The voice model's tools at this commit (`daemon.py`, `TOOLS`) have no action that interrupts a working agent; a message waits while the agent's shell command runs.
- Keyboard reference, redirect items: in 4 of 6 runs the agent ran nothing after Escape and the typed redirect and its last reply asked how to redirect (or which option to take). The keyboard arm has no scripted answer to questions, so the redirect column measures the agent and this scripted user more than the voice path; it does not separate the arms.

## Run-to-run (synthetic speech)

- a:pointe: 6 repeated items, flips 0, pass^2 17%.
- a:llm-router: 6 repeated items, flips 0, pass^2 50%.
- b:pointe: 8 repeated items, flips 5, pass^2 25%.
- b:llm-router: 8 repeated items, flips 0, pass^2 100%.

## Limits

- Synthetic speech only (four Kokoro voices, no noise): an upper bound for every arm. Kokoro is also Pointe's local voice.
- The reference arms (`naive`, `llm-router`, `keyboard`) were written by the team that builds Pointe. No outside product is tested.
- Spend is computed from token usage and list prices (Claude Code session usage; Pointe's daemon log with an assumed 300 output tokens a brain step and a flat allowance for its reader and checker), not metered by the vendors. Claude Code's own background calls (session titles) are not in its transcript.
- The machine ran other workloads, including other benchmark agents, during the runs; the runner waited up to 45 s (Part A) or 2 minutes (Part B, the latency result) for the 1-minute load average to fall under 12 before each run and flags rows that started above it. Latency rows with a flag are less reliable.
- Small samples: 18 stop-type items and 6 backchannels per arm in Part A, 30 questions in Part B. Intervals are wide; the tables do not rank arms whose intervals overlap.
- Part B's facts were read into the agent's context by a typed setup turn before the question (the same in every arm), so the time measures the voice path, not the agent's search.
- The agent's settings file allows the job's shell commands and a hook allows commands that stay inside the item repo, the same in every arm, so no permission prompt stands between the user and the outcome. The hook refuses any command with `..`, even one that stays inside the repo: such a run waits at a prompt and ends as capped.
- The scripted user answers a spoken question back (question detector, slot answers); it does not answer a question the agent asks in text on the keyboard arm.
- The run was resumed twice: once to shorten the load wait for Part A (from 2 minutes to 45 s, after 49 runs), once to run again the 6 Pointe runs that had failed to start because an earlier isolated daemon still held the port. The failed rows stay in rows.jsonl; the later row for the same run is the one counted. Each row carries the bench commit it ran at; Pointe's commit is the same in every row.
