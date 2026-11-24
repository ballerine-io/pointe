<!-- Written by bench/conversational/publish.py from the committed results. Do not edit by hand. -->

# Pointe Conversational Engineering Benchmarks

Five benchmarks of conversational engineering, measuring what a voice layer costs a coding agent. The agent is held fixed (claude-haiku-5-5 in Claude Code), and the same tasks reach it typed or spoken, so a score is the loss the voice interface adds, not the strength of the agent. Pointe is the system under test.

This is a reproducible self-evaluation with an adapter interface, not a leaderboard:

- **Synthetic speech.** Four clean Kokoro voices, also Pointe's local voice: an upper bound for every arm.
- **Every reference arm is ours.** The LLM router, the keyword rules and the keyboard arms were written by Pointe's team, who know Pointe's internals. No outside product is tested.
- **Small samples.** Intervals are wide. Where they overlap, no ranking is claimed.
- **Every number regenerates** from raw rows committed in `bench/conversational/<benchmark>/results/`.

Humanity's Last Keystroke is named after Humanity's Last Exam (CAIS and Scale AI, arXiv 2501.14249) and is not affiliated with it.

## At a glance (synthetic speech)

| benchmark | question | unit | Pointe | LLM router | keyboard reference |
|---|---|---|---|---|---|
| [Humanity's Last Keystroke (HLK)](hlk.md) | Is a small scripted coding task finished by voice only, when the keyboard version is finished? | task family (12 families, 36 tasks) | 27/72 passes | 62/72 | 70/72 |
| [Spoken Identifiers](identifiers.md) | When a symbol in the repository is spoken, does the agent change the right one and nothing else? | target symbol | 42/48 right | 39/45 | 24/24 |
| [Spoken Actions and False Approval](actions.md) | Does speech become the right harness action, and how often does something that is not a yes approve a destructive prompt? | utterance | accuracy 78/120; false approval 3/60 | 109/120; 2/60 | accuracy 30/30 |
| [Session Routing](routing.md) | With four live sessions, does a spoken request reach the right one, and is an ambiguous one asked about? | conversation | 49/60 turns | 55/60 | 19/20 |
| [Barge-in and Time to a Correct Answer](bargein.md) | Can speech stop, undo or redirect a working agent, and how long until the first correct spoken answer? | item | halted 0/18; answered 23/27 | 18/18; 27/27 | 18/18; 27/27 |

## Before and after the fixes (Pointe arm, synthetic speech)

The run of 2026-11-23 found five defects in Pointe: a send that delivered an earlier request after "which session?", no way to stop a running turn, permission requests only a tap could approve, misheard words rewritten into code names, and slow spoken answers. They were fixed the same day, and the Pointe arm of every benchmark was run again on the fixed build (2026-11-23) with the same agent model, items, seeds and settings. The reference arms run no Pointe code and keep their rows from the earlier run. That run's pages are kept as published: [earlier/2026-11-23/](earlier/2026-11-23/README.md).

The reruns of HLK and Spoken Actions ran while the brain model answered slowly: Pointe's 8 s limit on a brain step cut 26 of 72 HLK runs and 12 of 140 Spoken Actions runs, against 3 of 72 and 1 of 141 in the first run (Barge-in: 2 of 68, against 1 of 74). Their before and after differ in the vendor's latency as well as in Pointe. Launches that ran while it was slower still were stopped and are kept, not used.

| benchmark | measure | before (2026-11-23) | after |
|---|---|---|---|
| Humanity's Last Keystroke (HLK) | tasks passed | 34/72 = 47% (36-59%) | 27/72 = 38% (27-49%) |
| Spoken Identifiers | right symbol | 40/48 = 83% (70-91%) | 42/48 = 88% (75-94%) |
| Spoken Actions and False Approval | action accuracy | 85/120 = 71% (62-78%) | 78/120 = 65% (56-73%) |
| Spoken Actions and False Approval | false approval (lower is better) | 5/60 = 8% (4-18%) | 3/60 = 5% (2-14%) |
| Spoken Actions and False Approval | false denial (lower is better) | 10/20 = 50% (30-70%) | 10/20 = 50% (30-70%) |
| Spoken Actions and False Approval | missed stop (lower is better) | 8/8 = 100% (68-100%) | 8/8 = 100% (68-100%) |
| Session Routing | turns routed right | 41/60 = 68% (56-79%) | 49/60 = 82% (70-89%) |
| Barge-in and Time to a Correct Answer | A: job halted when told to stop | 0/18 (upper bound 18%) | 0/18 (upper bound 18%) |
| Barge-in and Time to a Correct Answer | B: correct answer within 45 s | 18/27 = 67% (48-81%) | 23/27 = 85% (68-94%) |
| Barge-in and Time to a Correct Answer | B: time to the correct answer, median / p90 | 27.9 s / 37.7 s (9 censored) | 26.7 s / 36.1 s (4 censored) |

## Pointe minus the LLM router, paired (synthetic speech)

The LLM router is the baseline: the same recognizer as Pointe's default setup and one call per utterance to the same brain model. Differences in percentage points with 95% bootstrap intervals over each benchmark's independent unit. Spoken Actions has no paired difference: its false-approval counts are too small and unstable to rank.

| measure | bootstrap unit | Pointe minus LLM router |
|---|---|---|
| HLK, tasks passed | task family (12 families, 36 tasks) | -49 points (-65 to -31) |
| Identifiers, right symbol | target symbol | +2 points (-12 to +15) |
| Routing, turns right | conversation | -10 points (-18 to -2) |
| Barge-in A, job halted | item | -42 points (-62 to -21) |
| Barge-in B, answered | item | -15 points (-30 to -4) |

## Run them on your harness

Each benchmark keeps its own harness (runner, adapters, speech corpus, scorer) in `bench/conversational/<benchmark>/`, frozen with the run that produced its results. To measure your own conversational harness:

1. `uv sync --locked --extra local`, then render the speech (`run.py corpus`) and run the offline checks: free, no keys. Each benchmark's page has its exact commands.
2. Write an adapter: it receives the same audio (or text) at real-time pace and reports what it delivered, approved or said. Each benchmark's page names the file to register it in.
3. Run `--smoke` first, then the full run with `--budget-usd`; the runner checks the spend ledger before every launch. Keys come from the macOS Keychain or the environment, into the one process that needs them.
4. `run.py report <run-id>` writes the tables. Send the rows and the adapter as a pull request.

## Spend

| benchmark | spend, every launch | cap |
|---|---|---|
| Humanity's Last Keystroke (HLK) | $43.11 | $55 |
| Spoken Identifiers | $8.09 | $12 |
| Spoken Actions and False Approval | $16.78 | $18 |
| Session Routing | $10.17 | $11 |
| Barge-in and Time to a Correct Answer | $6.02 | $14 |
| all five | $84.18 | $110 |

Computed from usage and list prices, not metered: smoke, debug, aborted runs and verification reruns are included, and so is the Pointe-arm rerun after the fixes. Two caps were raised for the rerun: Session Routing from $9 to $11, Spoken Actions from $17 to $18.

The speech-component benchmarks (recognizers, voices, brains) are a separate page: [docs/benchmarks.md](../benchmarks.md).
