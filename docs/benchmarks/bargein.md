<!-- Written by bench/conversational/publish.py from the committed results. Do not edit by hand. -->

# Barge-in and Time to a Correct Answer

*Can speech stop, undo or redirect a working agent, and how long until the first correct spoken answer?*

Part of the [Pointe Conversational Engineering Benchmarks](README.md): a self-evaluation with an adapter interface, on synthetic speech. Every reference arm was written by Pointe's team. Every number on this page is computed from the committed results; the Limits section is the benchmark's own README.

## Setup

- Independent unit: item. Sample: Part A: 18 stop, undo or redirect items and 6 backchannels; Part B: 27 status questions.
- Run bargein-20261123-040244, 2026-11-23.
- Agent claude-haiku-5-5 in Claude Code 2.1.330, acceptEdits, one worker.
- Pointe 7113efa: brain=anthropic:claude-sonnet-5-5, reader=anthropic:claude-sonnet-5-5, checker=gemini:gemini-3.5-flash-lite, ears=soniox, mouth=elevenlabs:eleven_v4_turbo.
- LLM router: the same brain model as Pointe, Soniox ears.

## Results

Part A: stop, undo and redirect a running job (synthetic speech, 95% Wilson intervals).

| arm | halted when told to stop | false stop on a backchannel | undo |
|---|---|---|---|
| Pointe | 0/18 (upper bound 18%) | 0/6 (upper bound 39%) | 0/4 |
| LLM router | 18/18 = 100% (82-100%) | 0/6 (upper bound 39%) | 2/4 |
| keyword rules, ours | 11/18 = 61% (39-80%) | 0/6 (upper bound 39%) | 0/4 |
| keyboard | 18/18 = 100% (82-100%) | 0/6 (upper bound 39%) | 4/4 |
| null (does nothing) | 0/5 (upper bound 43%) | 0/3 (upper bound 56%) | 0/2 |

Part B: status questions (synthetic speech). The keyboard row times correct text on the terminal, a different quantity.

| arm | correct answer within 45 s | time to the correct answer, median / p90 | correct within 10 s |
|---|---|---|---|
| Pointe | 18/27 = 67% (48-81%) | 27.9 s / 37.7 s (9 censored) | 0/27 |
| LLM router | 27/27 = 100% (88-100%) | 10.1 s / 14.6 s (0 censored) | 13/27 |
| keyword rules, ours | 27/27 = 100% (88-100%) | 9.7 s / 14.2 s (0 censored) | 16/27 |
| keyboard | 27/27 = 100% (88-100%) | 1.1 s / 1.7 s (0 censored) | 26/27 |

- Part A, Pointe minus LLM router paired by item: -42 points (-62 to -21). At this commit Pointe passes a spoken stop to the agent as a message and has no action that interrupts it (21 of 23 logs).
- Part B, Pointe minus LLM router: -33 points (-52 to -15).
- Redirect was 0/6 in every arm, the keyboard included: the column does not separate the arms.
- 3 branch questions (12 runs) are not scored because of a label error.
- The reference arms speak through local Kokoro; Pointe through ElevenLabs over the network. The Part B times include that difference.

Full results: [RESULTS.md](../../bench/conversational/bargein/bargein/RESULTS.md). Raw rows, events and spend: `bench/conversational/bargein/results/`. Spend on this benchmark, every launch included: $3.41 of a $14 cap, computed from usage and list prices, not a vendor bill.

## Limits

Synthetic speech (four clean Kokoro voices) is an upper bound for every arm, and Kokoro is also Pointe's local voice.
The reference arms are written by Pointe's team. Spend is computed from token usage and list prices, not metered.
Samples are small; the intervals say how small. See RESULTS.md for the limits of the published run.

The published run:

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

## Run it on your harness

The benchmark carries its own harness in `bench/conversational/bargein/`. Write an adapter in `bench/conversational/bargein/adapters/`, register it in `bargein/bench.py: make_adapter`, and run:

```
uv run --locked --extra local python bench/conversational/bargein/run.py corpus          # render the synthetic speech, $0
uv run --locked pytest -q tests/test_conversational_bargein.py   # offline checks, $0, no keys
uv run --locked --extra local python bench/conversational/bargein/run.py bargein --adapter yours --smoke
uv run --locked --extra local python bench/conversational/bargein/run.py bargein --adapter yours --budget-usd 14
uv run --locked --extra local python bench/conversational/bargein/run.py report <run-id>
```

Every arm starts the same agent with the same launch line in its own throwaway repository under `/tmp`; an adapter only decides how the words reach it. Details: [the benchmark's README](../../bench/conversational/bargein/bargein/README.md) and [its harness README](../../bench/conversational/bargein/README.md).
