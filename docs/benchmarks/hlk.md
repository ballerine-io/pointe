<!-- Written by bench/conversational/hlk/run.py report from the committed rows. Do not edit by hand. -->

# Humanity's Last Keystroke (HLK)

*a pilot voice-only coding benchmark, v0.1, synthetic speech, n = 36 in 12 families*

Part of Pointe's release benchmarks (docs/benchmarks/README.md): a self-evaluation harness with an adapter interface. One system under test (Pointe) and reference arms written by the same team, on synthetic speech. The authors know Pointe's internals. This is not a ranking of products.

HLK asks whether a small scripted multi-step coding task is finished by voice only, graded by hidden tests on the final state of the repository, compared with the keyboard on the same terminal. The coding agent is held fixed (claude-haiku-5-5 in Claude Code, permission mode acceptEdits), so the score is the loss the voice interface adds, not the strength of the agent. The tasks are small Python standard-library edits sized for that agent.

The name follows Humanity's Last Exam (CAIS and Scale AI, arXiv 2501.14249); HLK is not affiliated with it. Humanity's Last Exam has about 2,500 expert questions; HLK has 36 generated tasks: 36 instances in 12 families. Seeds only swap names and numbers, so the effective sample size is close to 12, the families, and the intervals are wide. The suite can show a large gap; it cannot rank two close systems.

## Limits, plainly

- Synthetic speech is an upper bound for everyone: four clean US and British Kokoro voices are easier than people. Every table title says synthetic speech.
- The arms do not hear or speak alike. The LLM router is handed each utterance whole after it ends, so it never decides when a turn is over; its recognizer call is retried on a dropped connection, and Pointe's live call is not. The router speaks through local Kokoro, which the scoring Whisper reads easily; Pointe speaks through ElevenLabs. The router's own decisions are not logged.
- Since 2026-11-25 an item passes only if its task reached the agent (a user prompt between the first scripted turn and the final question), and the agent's folder has an opaque name: the earlier runs named the item ("impossible-as-stated-2-…") and the arm in the path, which agents read aloud.
- No outside product is tested. Every reference arm is written by Pointe's team; we found no way to give audio to another voice coding tool without a virtual microphone, and the rules forbid microphones.
- Pointe's own model sits between the user and the agent and may rewrite an instruction, so a spoken arm can beat the keyboard arm.
- The keyboard (canonical) text is written as a person would type it, and in some families it carries a detail the spoken line leaves to the listener (a file name in brackets, a quoted value), so the gap against it mixes information with voice; the router is the like-for-like comparison.
- The scripted user is deterministic, not a person: it answers the questions an item foresees, says one generic line to any other question, and repeats an instruction at most once.
- Costs are computed from usage and list prices, not metered bills.
- Voice only means voice only. Pointe counts a spoken yes only after it has read the request in full, and reads a command without a short form word for word; the scripted user cannot tap, so after two spoken yeses that did not take it says no. The count is in the table below.
- Other benchmark processes shared the machine during the runs; no row started while the 1-minute load was over 20, and the load at each row's start and end is in the row. Times are wall-clock times of one laptop and one network.
- One item does not say all that it scores: spelled-out seed 2 spells a dunder name letter by letter and does not say its case, and the hidden test wants lower case. It stays as frozen. Passes on it: keyboard, canonical 3 of 3, Pointe 1 of 3, LLM router 3 of 3, null (does nothing) 0 of 1.

Runs: hlk-20261125-170854. Dates: 2026-11-25. Agent: claude-haiku-5-5 in Claude Code 2.1.332. Pointe: 756088c, frozen before its first paid row (2026-11-25). Router brain: anthropic:claude-sonnet-5-5. Spoken output of every arm is read by one pinned local Whisper (large-v3-turbo).

Every planned run finished inside the cap; nothing was trimmed.

## Passes per family (synthetic speech)

Cells are passes over runs of the 3 instances of a family (3 runs of each). A pass is: the task reached the agent, the hidden tests pass and the protected files are unchanged; for impossible-as-stated, the files are unchanged and the answer to the last question is an explicit no.

| family | group | keyboard, canonical | Pointe | LLM router | null (does nothing) |
|---|---|---|---|---|---|
| twin-symbols | naming | 9/9 | 1/9 | 7/9 | 0/3 |
| homophone-files | naming | 9/9 | 8/9 | 7/9 | 0/3 |
| dictated-literals | naming | 9/9 | 9/9 | 9/9 | 0/3 |
| spelled-out | naming | 9/9 | 7/9 | 9/9 | 0/3 |
| noisy-paths | naming | 9/9 | 7/8 | 9/9 | 0/3 |
| self-correction | language | 9/9 | 7/9 | 9/9 | 0/3 |
| long-dictation | language | 9/9 | 4/7 | 9/9 | 0/3 |
| read-then-decide | language | 9/9 | 9/9 | 9/9 | 0/3 |
| deny-the-decoy | control | 8/9 | 9/9 | 9/9 | 0/3 |
| mid-task-redirect | control | 9/9 | 7/9 | 0/9 | 0/3 |
| two-repo-handoff | control | 9/9 | 8/9 | 9/9 | 0/3 |
| impossible-as-stated | control | 6/9 | 9/9 | 7/9 | 0/3 |
| all 12 families |  | 104/108 | 85/105 | 93/108 | 0/36 |

## The voice gap (synthetic speech)

Keyboard minus the spoken arm, in percentage points, paired by family, with a 95% bootstrap interval over the 12 families. A negative gap means the spoken arm passed more often.

| spoken arm | keyboard, canonical minus it | keyboard, transcript minus it |
|---|---|---|
| Pointe | +15 points (95% CI +0 to +33) | not run |
| LLM router | +10 points (95% CI -2 to +29) | not run |

Pointe minus the LLM router, paired by family: -5 points (95% CI -23 to +15).

Overall pass rates (runs, not independent; for orientation only): keyboard, canonical 104 of 108, 96% (95% CI 91 to 99%); Pointe 85 of 105, 81% (95% CI 72 to 87%); LLM router 93 of 108, 86% (95% CI 78 to 91%); null (does nothing) 0 of 36 (95% upper bound 10%).

## Claims at the end of the task, paired (synthetic speech)

Every task ends with "Is it done, and do the tests pass? Yes or no." False done is a yes on a run that failed, over the failed runs; false not done is a no on a run that passed, over the passed runs. The denominators are small, so this is not a robust number. An answer that cannot be read is no claim.

| arm | false done | false not done | no claim |
|---|---|---|---|
| keyboard, canonical | 4 of 4, 100% (95% CI 51 to 100%) | 14 of 104, 13% (95% CI 8 to 21%) | 0 |
| Pointe | 14 of 20, 70% (95% CI 48 to 85%) | 6 of 85, 7% (95% CI 3 to 15%) | 3 |
| LLM router | 8 of 15, 53% (95% CI 30 to 75%) | 9 of 93, 10% (95% CI 5 to 17%) | 1 |
| null (does nothing) | 0 of 36 (95% upper bound 10%) | n = 0 | 36 |

## Stability, effort, time and spend (synthetic speech)

| arm | pass^k (items) | flips (items) | clarifications per task | corrective turns per task | time median / p90 | spend per task | capped | invalid (out of tree) | errors | no said after two yeses did not take |
|---|---|---|---|---|---|---|---|---|---|---|
| keyboard, canonical | 34/36 | 0/36 | 0.03 | 0.00 | 32 s / 44 s | $0.003 | 0 | 0 | 0 | 0 |
| Pointe | 24/36 | 7/36 | 0.09 | 0.03 | 128 s / 170 s | $0.217 | 0 | 3 | 0 | 0 |
| LLM router | 30/36 | 2/36 | 0.13 | 0.01 | 176 s / 268 s | $0.013 | 0 | 0 | 0 | 0 |
| null (does nothing) | n/a | n/a | 0.00 | 0.92 | 27 s / 30 s | $0.000 | 0 | 0 | 0 | 0 |

pass^k: instances whose every run passed. Flips: instances whose first two runs disagree. A clarification is a question the item foresaw, answered (no penalty); a corrective turn is a repeated instruction. Capped runs (12 user turns, 10 minutes, or $0.60) count as failures. Invalid runs named a path outside the item's folder in a tool call and are excluded from the passes. Errors are runs the harness could not finish; they count as failures.

In none of Pointe's 20 failed runs did a spoken yes fail to take.

Harness faults: a run in which Claude Code showed a permission prompt without firing its hook, the runner credited an answer to the wrong request, or the agent made no step for 8 minutes was rerun once with the same voice and run index, by that rule and in every arm. Reruns: none. The first rows stay in the raw data.

## Passes by stressor group (synthetic speech)

| group | keyboard, canonical | Pointe | LLM router | null (does nothing) |
|---|---|---|---|---|
| naming | 45/45 | 32/44 | 41/45 | 0/15 |
| language | 27/27 | 20/25 | 27/27 | 0/9 |
| control | 32/36 | 33/36 | 25/36 | 0/12 |

## How it was measured

- One launch line for every arm: interactive claude --model claude-haiku-5-5 --permission-mode acceptEdits in a pseudo-terminal in the task repository, with a fresh CLAUDE_CONFIG_DIR and the API key in its environment only (Bash commands still ask). The Pointe arm adds only --plugin-dir and joins with /pointe:voice. No arm uses claude -p or --bare. A preflight checked that sessions are billed to the API key, load no user plugins and run in acceptEdits.
- Arms run: keyboard, canonical (the instruction as a person would type it; approve, deny and Escape as keypresses at the same triggers; the reference ceiling); null (starts the sessions, does nothing: the floor); LLM router (Soniox ears, one call per utterance to the brain model of Pointe's default setup with a published 20-line prompt, speech through local Kokoro: the baseline for the head-to-head); Pointe (an isolated daemon in its default setup, audio in over the page's call, audio out recorded).
- Answer keys: hidden tests and the reference patch are written before the session to a folder no arm is given; every config dir denies reads of it and of the bench; every transcript was audited for tool calls naming a path outside the item.
- Scripted user: triggers, slot answers, a question detector (final sentence a question, a wh-word or an auxiliary first, or phrases such as "which one"). On 48 labelled lines rendered by Kokoro and read by Whisper it was right on 48 (100%).
- Item order was shuffled by a recorded seed and the runner went item by item across all arms in one launch, so every arm met the same hours of vendor latency, and a stop at the budget would have left a random subsample with every arm present.
- Speech: Kokoro-82M v1.0 (Apache-2.0), four voices (US and British, female and male), one seeded voice per instance for every run; noise made in code (babble from the three other voices at 6 dB for the noisy-paths instruction, pink noise at 12 dB for the rest of that item).

## Run it, add to it

```
uv run --locked --extra local python bench/conversational/hlk/run.py corpus
uv run --locked --extra local python bench/conversational/hlk/run.py verify
HLK_POINTE_CHECKOUT=<a checkout at the frozen commit> uv run --locked --extra local python bench/conversational/hlk/run.py hlk --adapter keyboard-canonical,null,llm-router,pointe --runs 3 --workers 2 --port-base 9300 --budget-usd <the ledger's total plus this run>
```

An adapter implements start, say, type, key, events, speech, versions, spend and stop (bench/conversational/hlk/core/adapter.py); a missing capability shows as coverage, never as a failure. A family is a generator in bench/conversational/hlk/hlk/families/; hlk/CONTRIBUTING.md says how, and run.py verify (free) proves its check goes red and green. Accepted authors are named here. A better router prompt is welcome as a pull request. Family authors so far: the Pointe team.

Spend: $68.69 for HLK in all, every launch since 2026-11-23 (smoke and debugging included), computed from usage and list prices in bench/conversational/hlk/prices.json. Raw rows and the final files of every published run (run.py verify re-scores them): bench/conversational/hlk/results/. Text and tasks CC BY 4.0, code MIT.
