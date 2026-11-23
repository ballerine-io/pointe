<!-- The published run of 2026-11-23, before the fixes of what it found (Pointe 6544cdc; barge-in 7113efa). Kept as published; links point at its own files. -->

# Pointe Conversational Coding Benchmarks

Five benchmarks of what a voice layer costs a coding agent. The agent is held fixed (claude-haiku-5-5 in Claude Code), and the same tasks reach it typed or spoken, so a score is the loss the voice interface adds, not the strength of the agent. Pointe is the system under test.

This is a reproducible self-evaluation with an adapter interface, not a leaderboard:

- **Synthetic speech.** Four clean Kokoro voices, also Pointe's local voice: an upper bound for every arm.
- **Every reference arm is ours.** The LLM router, the keyword rules and the keyboard arms were written by Pointe's team, who know Pointe's internals. No outside product is tested.
- **Small samples.** Intervals are wide. Where they overlap, no ranking is claimed.
- **Every number regenerates** from raw rows committed in `bench/conversational/<benchmark>/results/`.

Humanity's Last Keystroke is named after Humanity's Last Exam (CAIS and Scale AI, arXiv 2501.14249) and is not affiliated with it.

## At a glance (synthetic speech)

| benchmark | question | unit | Pointe | LLM router | keyboard reference |
|---|---|---|---|---|---|
| [Humanity's Last Keystroke (HLK)](hlk.md) | Is a small scripted coding task finished by voice only, when the keyboard version is finished? | task family (12 families, 36 tasks) | 34/72 passes | 62/72 | 70/72 |
| [Spoken Identifiers](identifiers.md) | When a symbol in the repository is spoken, does the agent change the right one and nothing else? | target symbol | 40/48 right | 39/45 | 24/24 |
| [Spoken Actions and False Approval](actions.md) | Does speech become the right harness action, and how often does something that is not a yes approve a destructive prompt? | utterance | accuracy 85/120; false approval 5/60 | 109/120; 2/60 | accuracy 30/30 |
| [Session Routing](routing.md) | With four live sessions, does a spoken request reach the right one, and is an ambiguous one asked about? | conversation | 41/60 turns | 55/60 | 19/20 |
| [Barge-in and Time to a Correct Answer](bargein.md) | Can speech stop, undo or redirect a working agent, and how long until the first correct spoken answer? | item | halted 0/18; answered 18/27 | 18/18; 27/27 | 18/18; 27/27 |

## Pointe minus the LLM router, paired (synthetic speech)

The LLM router is the baseline: the same recognizer as Pointe's default setup and one call per utterance to the same brain model. Differences in percentage points with 95% bootstrap intervals over each benchmark's independent unit. Spoken Actions has no paired difference: its false-approval counts are too small and unstable to rank.

| measure | bootstrap unit | Pointe minus LLM router |
|---|---|---|
| HLK, tasks passed | task family (12 families, 36 tasks) | -39 points (-62 to -15) |
| Identifiers, right symbol | target symbol | -2 points (-10 to +6) |
| Routing, turns right | conversation | -23 points (-32 to -15) |
| Barge-in A, job halted | item | -42 points (-62 to -21) |
| Barge-in B, answered | item | -33 points (-52 to -15) |

## Run them on your harness

Each benchmark keeps its own harness (runner, adapters, speech corpus, scorer) in `bench/conversational/<benchmark>/`, frozen with the run that produced its results. To measure your own conversational harness:

1. `uv sync --locked --extra local`, then render the speech (`run.py corpus`) and run the offline checks: free, no keys. Each benchmark's page has its exact commands.
2. Write an adapter: it receives the same audio (or text) at real-time pace and reports what it delivered, approved or said. Each benchmark's page names the file to register it in.
3. Run `--smoke` first, then the full run with `--budget-usd`; the runner checks the spend ledger before every launch. Keys come from the macOS Keychain or the environment, into the one process that needs them.
4. `run.py report <run-id>` writes the tables. Send the rows and the adapter as a pull request.

## Spend

| benchmark | spend, every launch | cap |
|---|---|---|
| Humanity's Last Keystroke (HLK) | $24.35 | $55 |
| Spoken Identifiers | $4.88 | $12 |
| Spoken Actions and False Approval | $8.67 | $17 |
| Session Routing | $6.31 | $9 |
| Barge-in and Time to a Correct Answer | $3.41 | $14 |
| all five | $47.62 | $107 |

Computed from usage and list prices, not metered: smoke, debug, aborted runs and verification reruns are included.

The speech-component benchmarks (recognizers, voices, brains) are a separate page: [docs/benchmarks.md](../../../benchmarks.md).
