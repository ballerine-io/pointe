# bargein: Barge-in and Time to a Correct Answer

Part of the Pointe Conversational Coding Benchmarks (design revision 2, section 5.5). A reproducible
self-evaluation on **synthetic speech**, not a leaderboard. Results: [RESULTS.md](RESULTS.md).

**Measures.** (A) whether speech can stop or redirect a coding agent in the middle of a task, judged by the final
repository state; (B) the time from the end of the user's speech to the first answer that is correct, beside the time
to first audio that other latency benchmarks report.

## Run

```
uv sync --locked --extra local            # Whisper and Kokoro, both pinned in assets.py; nothing else is downloaded
uv run --locked --extra local python bench/conversational/bargein/run.py bargein --budget-usd 14 --dry-run    # the plan, $0
uv run --locked --extra local python bench/conversational/bargein/run.py corpus      # render the audio, $0
uv run --locked --extra local python bench/conversational/bargein/run.py factcheck   # the fact matcher on Whisper, $0
uv run --locked --extra local python bench/conversational/bargein/run.py freeze      # FROZEN.json; commit it before paid rows
uv run --locked --extra local python bench/conversational/bargein/run.py bargein --budget-usd 14 [--adapter pointe,llm-router,naive,keyboard,null] [--smoke] [--pointe-setup <id>]
uv run --locked --extra local python bench/conversational/bargein/run.py report <run-id>
```

Options: `--port-base` (default 9700; 7860 and 7443 are refused), `--workers` (must be 1: local Whisper, Kokoro and
parallel workers on one machine corrupt latency), `--resume <run-id>`, `--items <glob>`, `--debug` (ledger rows marked
debug, never published). Keys come from the environment or the macOS Keychain (Pointe's item names), and reach only
the process that needs them. Needs an Apple-silicon Mac for the local models, Claude Code, `uv`, and keys for
Anthropic and Soniox (plus ElevenLabs and Gemini for Pointe's default setup).

## Dataset

- **Part A, 24 items** (`items.toml`, one Kokoro voice each by seeded draw). The fixture `fixture/longjob` ships
  `long_job.sh`, which writes `step_01.txt` to `step_20.txt` with `sleep 2` between. The agent is told to run it and
  nothing else; a run where it does anything else before the trigger is `setup_failed`. When `step_03.txt` exists
  the scripted user acts: stop (8), stop and undo (4), redirect to `out/` (6), or a backchannel that must not stop it
  (6).
- **Part B, 30 questions** (one voice each) on `fixture/status`, a status file whose facts survive speech recognition
  (seven failed tests, the build did not pass, port 8080, ...). A typed setup turn, the same in every arm, has the
  agent read the file before the question. The item repo is on the branch the file names (`cedar`); the run of
  2026-11-23 had it on `master`, so its three branch questions are not scored (RESULTS.md).
- The scripted user answers a question back once per slot ("Want me to ask it?" gets "Yes, please."; a backchannel
  item's confirm gets "No, keep going."; anything else gets "Please go on with what I asked."). The question detector
  scores 100% on 40 labelled lines rendered and recognized (`factcheck.json`).

Independent unit: the item. Fixture names (`kiln`, `quarry`, `garden`, `cedar`, `voucher`) occur nowhere in Pointe's
own tests or benches (tested).

## Arms

Every arm starts `claude --model claude-haiku-5-5 --permission-mode acceptEdits` in a pty, in the item's repo under
`/tmp/pccb/<run-id>/`, with a fresh `CLAUDE_CONFIG_DIR` and the API key in its environment only (a preflight probe
asserts the API-key source). The settings file, the same in every arm, allows the job's commands and adds a hook that
lets a shell command run when it stays inside the item repo, so no permission prompt stands between the user and the
outcome.

| Arm | What it is |
|---|---|
| `pointe` | Pointe at the frozen commit, exported to `/tmp`, on its own daemon (state folder and ports from the runner's range). The session adds `--plugin-dir` and joins with `/pointe:voice`. Audio goes in over the page's call; the call's audio out is recorded. Setup: none chosen, so each role takes the first vendor with a key (Sonnet brain and reader, Soniox ears, ElevenLabs mouth, Gemini checker); `--pointe-setup` picks another. |
| `llm-router` | The baseline for the comparison: Soniox ears (Pointe's default recognizer), one call per utterance to the same brain model with the public prompt `adapters/llm_router_prompt.txt`, one JSON action (`stop` sends Escape; `send` types, after Escape when `interrupt` is true), the agent's final message spoken through local Kokoro. |
| `naive` | Keyword rules, ours: "stop" or "cancel" sends Escape; anything else is typed in. Local Kokoro out. |
| `keyboard` | The reference: Escape and the typed text at the same trigger. In Part B its time is time to correct text on the terminal, a different quantity shown in its own column. |
| `null` | Starts the session and does nothing: the floor, on a seeded 8 items in Part A. |

Repeats for the flip rate: 6 Part A items and 8 Part B items, for `pointe` and `llm-router`.

## Scoring

Part A, from the file system: **halt** (the job never wrote `step_20.txt` in the repo root); **overshoot** (step files
written after the end of the user's speech, minus one in flight; the job's resolution is 2 s); **time to halt**;
**redirect** (the job stopped, `out/` ends with steps 04 to 20, steps 01 to 03 left in place or moved to `out/`, both
accepted, and no step above 03 outside `out/` beyond the one in flight); **undo**; **false stop** on backchannels
printed beside **missed stop**. Part B: correct-answer rate; time to first audio; **TTCA**, the end of the first
utterance that states the fact, median and p90 over correct answers; share correct within 10 s and 30 s; items never
answered correctly within 45 s are censored and counted. Spoken output is matched on the recorded audio through the
one pinned Whisper large-v3-turbo, the same for every adapter. One clock: the runner's monotonic clock at audio frame
send and receive. Proportions carry 95% Wilson intervals with counts; the load average is in every row, and rows that
start above 12 are flagged.

## Licenses

Text (items, fixtures) CC BY 4.0; code MIT; audio rendered by Kokoro-82M (Apache-2.0). Synthetic only: every name
is invented and no recording of a person is used.

## Limits

Synthetic speech (four clean Kokoro voices) is an upper bound for every arm, and Kokoro is also Pointe's local voice.
The reference arms are written by Pointe's team. Spend is computed from token usage and list prices, not metered.
Samples are small; the intervals say how small. See RESULTS.md for the limits of the published run.
