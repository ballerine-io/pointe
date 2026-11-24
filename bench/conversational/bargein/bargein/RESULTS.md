# bargein: Barge-in and Time to a Correct Answer (synthetic speech), v0.1

A reproducible self-evaluation on synthetic speech, not a leaderboard. One system under test (Pointe) and reference arms written by the same team. Every number below is computed by `run.py report` from the committed rows.

Runs: bargein-20261123-040244, bargein-20261123-161151. Dates: 2026-11-23 to 2026-11-23. Agent: `claude-haiku-5-5` in Claude Code 2.1.330, `--permission-mode acceptEdits`, one worker. Pointe: a pre-release build (2026-11-23) with the benchmark fixes; setup (default) (brain=anthropic:claude-sonnet-5-5, reader=anthropic:claude-sonnet-5-5, checker=gemini:gemini-3.5-flash-lite, ears=soniox, mouth=elevenlabs:eleven_v4_turbo, notes=[]). Spend: $2.87 in these rows; $6.02 for bargein in the ledger with adapter debugging and preflight probes, of a $14.00 cap (computed from token usage and list prices, not metered).

## Part A: stopping a working agent (synthetic speech, 24 items, one Kokoro voice each)

| Arm | Halt (stop, undo, redirect) | Missed stop | False stop on backchannels | Overshoot, files (median / p90) | Time to halt, stop items (median / p90) | Redirect | Undo | Stayed stopped (stop, undo) | Setup failed / errors / capped | Load-flagged |
|---|---|---|---|---|---|---|---|---|---|---|
| pointe | 0/18 (upper bound 18%) | 18/18 = 100% [82%, 100%] | 0/6 (upper bound 39%) | n/a (0 censored) | n/a (8 censored) | 0/6 (upper bound 39%) (left 0, moved 0) | 0/4 (upper bound 49%) | 0/12 (upper bound 24%) | 0 / 0 / 9 | 18 of 24 |
| llm-router | 18/18 = 100% [82%, 100%] | 0/18 (upper bound 18%) | 0/6 (upper bound 39%) | 1.50 / 2.00 (0 censored of 18) | 3.19 s / 4.84 s (0 censored of 8) | 0/6 (upper bound 39%) (left 0, moved 0) | 2/4 = 50% [15%, 85%] | 12/12 = 100% [76%, 100%] | 0 / 0 / 0 | 5 of 24 |
| naive | 11/18 = 61% [39%, 80%] | 7/18 = 39% [20%, 61%] | 0/6 (upper bound 39%) | 0.00 / 1.00 (0 censored of 11) | 1.27 s / 2.62 s (1 censored of 8) | 0/6 (upper bound 39%) (left 0, moved 0) | 0/4 (upper bound 49%) | 11/12 = 92% [65%, 99%] | 0 / 0 / 0 | 5 of 24 |
| keyboard | 18/18 = 100% [82%, 100%] | 0/18 (upper bound 18%) | 0/6 (upper bound 39%) | 0.00 / 0.00 (0 censored of 18) | 0.00 s / 0.00 s (0 censored of 8) | 0/6 (upper bound 39%) (left 0, moved 0) | 4/4 = 100% [51%, 100%] | 12/12 = 100% [76%, 100%] | 0 / 0 / 1 | 2 of 24 |
| null | 0/5 (upper bound 43%) | 5/5 = 100% [57%, 100%] | 0/3 (upper bound 56%) | n/a (0 censored) | n/a (2 censored) | 0/1 (upper bound 79%) (left 0, moved 0) | 0/2 (upper bound 66%) | 0/4 (upper bound 49%) | 0 / 0 / 0 | 3 of 8 |

`null` ran on a seeded 8 items: the job runs to its end by construction and each run still costs an agent session, so the floor is confirmed on a sample. Halt means the job that was running when the user spoke stopped before `step_20.txt` (its files come every 2 s; a file after a gap of more than 4 s belongs to a later run the agent started); stayed stopped means no later run wrote step files in the repo root either. Time to halt is the last root step file's time after the end of the user's speech (or the keypress), at the job's 2 s resolution. Overshoot is files written after that point minus one file in flight. A redirect counts when the job stopped, `out/` ends with steps 04 to 20, and steps 01 to 03 are either left in place or moved to `out/` (both accepted).

## Part B: time to the first correct answer (synthetic speech, 27 questions, one Kokoro voice each)

| Arm | Correct within 45 s | First audio (median / p90) | Time to correct answer (median / p90, censored) | Correct within 10 s | Correct within 30 s | Clarifications | Load-flagged |
|---|---|---|---|---|---|---|---|
| pointe | 23/27 = 85% [68%, 94%] | 5.78 s / 14.16 s (0 censored of 27) | 26.70 s / 36.08 s (4 censored of 27) | 0/27 (upper bound 12%) | 17/27 = 63% [44%, 78%] | 0 | 1 of 27 |
| llm-router | 27/27 = 100% [88%, 100%] | 5.55 s / 8.26 s (0 censored of 27) | 10.13 s / 14.57 s (0 censored of 27) | 13/27 = 48% [31%, 66%] | 26/27 = 96% [82%, 99%] | 0 | 2 of 27 |
| naive | 27/27 = 100% [88%, 100%] | 3.89 s / 6.68 s (0 censored of 27) | 9.66 s / 14.24 s (0 censored of 27) | 16/27 = 59% [41%, 75%] | 25/27 = 93% [77%, 98%] | 0 | 2 of 27 |
| keyboard (time to correct text, not comparable with spoken times) | 27/27 = 100% [88%, 100%] | n/a (text) | 1.11 s / 1.72 s (0 censored of 27) | 26/27 = 96% [82%, 99%] | 27/27 = 100% [88%, 100%] | 0 | 1 of 27 |

Times run from the end of the user's speech (keyboard: the Enter key) on the runner's monotonic clock. Spoken answers are scored on the recorded audio through the one pinned Whisper large-v3-turbo, the same for every arm; an item never answered correctly within 45 s is censored and counted beside each median. When an arm asks a question back, the scripted user answers it once (a clarification, not a penalty) and the clock keeps running from the first question.

Not scored: the 3 `branch` questions (b25, b26, b27; 9 runs), a label error: the runner made each fixture a fresh git repo on `master` while STATUS.md, the label, says `cedar`; most agents checked git and answered `master`. The keyboard arm was credited for printing `cedar` beside it; Whisper at times hears the spoken arms' "cedar" as "CDER". Fixed in the runner (the repo is now on `cedar`); these rows are not scored.

## Pointe against llm-router, paired by item (synthetic speech)

- Part A success (halt, undo, redirect; no false stop): Pointe 6/24, llm-router 16/24, difference -42% [95% bootstrap over items -62%, -21%].
- Part B correct answer: Pointe 23/27, llm-router 27/27, difference -15% [95% bootstrap over items -30%, -4%].

## What the raw logs show (counted by `run.py report` from events.jsonl)

- Pointe, Part A stop, undo and redirect runs (repeats included): in 9 of 23 the daemon log shows the spoken request sent to the session as a message (`-> kiln:`), and in 9 of those the job still ran to its end. In 20 of them the daemon log shows the spoken stop taken by the harness (`stop by voice: ... taken`): Claude Code ends the turn at its next tool step, through its hooks, so the job, one shell command, runs to its end first. Claude Code offers no supported way for another process to cut a running turn.
- Keyboard reference, redirect items: in 4 of 6 runs the agent ran nothing after Escape and the typed redirect and its last reply asked how to redirect (or which option to take). The keyboard arm has no scripted answer to questions, so the redirect column measures the agent and this scripted user more than the voice path; it does not separate the arms.
- Pointe, Part B runs (repeats included): in 0 of 38 the daemon log shows a permission request after the question: the voice model sent the agent to check the repo, and the agent ran a command outside the item repo, which the settings file does not allow. The scripted user answers no permission prompt.

## Run-to-run (synthetic speech)

- a:pointe: 6 repeated items, flips 0, pass^2 17%.
- a:llm-router: 6 repeated items, flips 0, pass^2 50%.
- b:pointe: 8 repeated items, flips 3, pass^2 62%.
- b:llm-router: 8 repeated items, flips 0, pass^2 100%.

## Limits

- Synthetic speech only (four Kokoro voices, no noise): an upper bound for every arm. Kokoro is also Pointe's local voice.
- The arms do not share a mouth: the reference arms speak the agent's reply through local Kokoro (no network), Pointe through its default ElevenLabs voice over the network. First audio and time to a correct answer include that difference, and the one Whisper transcribes two different voices.
- The reference arms (`naive`, `llm-router`, `keyboard`) were written by the team that builds Pointe. No outside product is tested.
- The llm-router prompt was written with the items: the acknowledgements it gives as examples ("mm-hm", "okay", "right") are words of the backchannel items. Backchannels do not separate the arms: no arm made a false stop, the keyword arm included.
- The fact matcher is regular expressions, checked on canonical answers in every voice. On the run's own answers it gave one false positive (a "no" that began "No build has run"); the matcher was fixed and every row re-scored from its raw log. No person or model judges the answers.
- Spend is computed from token usage and list prices (Claude Code session usage; Pointe's daemon log with an assumed 300 output tokens a brain step and a flat allowance for its reader and checker), not metered by the vendors. Claude Code's own background calls (session titles) are not in its transcript.
- The machine ran other workloads, including other benchmark agents, during the runs; the runner waited up to 45 s (Part A) or 2 minutes (Part B, the latency result) for the 1-minute load average to fall under 12 before each run and flags rows that started above it. Latency rows with a flag are less reliable.
- Small samples: 18 stop-type items and 6 backchannels per arm in Part A, 27 scored questions in Part B. Intervals are wide; the tables do not rank arms whose intervals overlap.
- Part B's facts were read into the agent's context by a typed setup turn before the question (the same in every arm), so the time measures the voice path, not the agent's search.
- The agent's settings file allows the job's shell commands and a hook allows commands that stay inside the item repo, the same in every arm, so the job's own commands never wait at a prompt; a command outside the item repo still does, and the scripted user answers no prompt. The hook refuses any command with `..`, even one that stays inside the repo: such a run waits at a prompt and ends as capped.
- The scripted user answers a spoken question back (question detector, slot answers); it does not answer a question the agent asks in text on the keyboard arm.
- The run was resumed twice: once to shorten the load wait for Part A (from 2 minutes to 45 s, after 49 runs), once to run again the 6 Pointe runs that had failed to start because a Pointe daemon started from /tmp still held the port (once visibly another benchmark's, run on the same machine and ports). The failed rows stay in rows.jsonl; the later row for the same run is the one counted. Each row carries the bench commit it ran at; Pointe's commit is the same in every row.
- The Pointe arm was run again after Pointe fixed what this suite found (bargein-20261123-161151, Pointe: a pre-release build (2026-11-23) with the benchmark fixes, the same items, voices, seeds and settings); each arm's rows come from the last run given that ran it, so the reference arms keep their rows from bargein-20261123-040244. The statements above about resumes and Pointe's commit describe that earlier run. The branch questions are left out for every arm, so both runs score the same items.
