<!-- Written by bench/conversational/hlk/run.py report from the committed rows. Do not edit by hand. -->

# Humanity's Last Keystroke (HLK)

*a pilot voice-only coding benchmark, v0.1, synthetic speech, n = 36 in 12 families*

Part of the Pointe Conversational Engineering Benchmarks: a reproducible self-evaluation harness with an adapter interface. One system under test (Pointe) and reference arms written by the same team, on synthetic speech. The authors know Pointe's internals. This is not a ranking of products.

HLK asks whether a small scripted multi-step coding task is finished by voice only, graded by hidden tests on the final state of the repository, compared with the keyboard on the same terminal. The coding agent is held fixed (claude-haiku-5-5 in Claude Code, permission mode acceptEdits), so the score is the loss the voice interface adds, not the strength of the agent. The tasks are small Python standard-library edits sized for that agent.

The name follows Humanity's Last Exam (CAIS and Scale AI, arXiv 2501.14249); HLK is not affiliated with it. Humanity's Last Exam has about 2,500 expert questions; HLK has 36 generated tasks: 36 instances in 12 families. Seeds only swap names and numbers, so the effective sample size is close to 12, the families, and the intervals are wide. The suite can show a large gap; it cannot rank two close systems.

## Limits, plainly

- Synthetic speech favours Pointe and is an upper bound for everyone: Kokoro, the text-to-speech here, is also Pointe's local voice, and four clean US and British voices are easier than people. Every table title says synthetic speech.
- No outside product is tested. Every reference arm is written by Pointe's team; we found no way to give audio to another voice coding tool without a virtual microphone, and the rules forbid microphones.
- Pointe's own model sits between the user and the agent and may rewrite an instruction, so a spoken arm can beat the keyboard arm. The keyboard-transcript arm (the exact spoken words, typed) helps read that.
- The scripted user is deterministic, not a person: it answers the questions an item foresees, says one generic line to any other question, and repeats an instruction at most once.
- Costs are computed from usage and list prices, not metered bills.
- The keyword-rules arm is ours and is built to fail the adversarial items; no headline number compares Pointe with it.
- Voice only means voice only. Pointe takes no spoken yes for a permission request it cannot read out and asks for a tap; the scripted user cannot tap, so after two spoken yeses that did not take it says no, as Pointe offers. The count is in the table below. A person at the machine would tap instead.
- Other benchmark processes shared the machine during the runs; the load average is in every row. Times are wall-clock times of one laptop and one network.
- The scripted user asks its next line after about four seconds of quiet. Pointe says an agent's question aloud a few seconds after the agent asks it, so in some of Pointe's failed runs the user asked its last question before Pointe had said the agent's question, and that question went unanswered (seen in the runs' trace logs, which are not committed). This counts against Pointe; the typed arms read the terminal and cannot hit it.
- One item does not say all that it scores: spelled-out seed 2 spells a dunder name letter by letter and does not say its case, and the hidden test wants lower case. It stays as frozen. Passes on it: keyboard, canonical 2 of 2, keyboard, transcript 0 of 2, Pointe 0 of 2, LLM router 2 of 2, keyword rules, ours 0 of 2, null (does nothing) 0 of 1.
- The first-run rows ran on the benchmark at commit 5d92037. A fault of that runner (an approval answer credited to the next request) was fixed after the run; the rows it hit were rerun by the rule below, at commit 84fb244.
- The Pointe arm was run again after Pointe fixed what this suite found: Pointe 84eafbc, the same agent, instances, voices, seeds and settings. The reference arms run no Pointe code; their rows come from the earlier runs (hlk-20261123-040919, hlk-20261123-085104, Pointe 6544cdc). The earlier page is kept as published in docs/benchmarks/earlier/.

Runs: hlk-20261123-040919, hlk-20261123-085104, hlk-20261123-161156. Dates: 2026-11-23. Agent: claude-haiku-5-5 in Claude Code 2.1.330. Pointe commit 84eafbccc24a (frozen before its first paid row, 2026-11-23). Router brain: anthropic:claude-sonnet-5-5. Spoken output of every arm is read by one pinned local Whisper (large-v3-turbo).

Every planned run finished inside the cap; nothing was trimmed.

## Passes per family (synthetic speech)

Cells are passes over runs: each paid arm ran each of the 3 instances of a family twice (6 runs); null ran once (3). A pass is: the hidden tests pass and the protected files are unchanged; for impossible-as-stated, the files are unchanged and the answer to the last question is an explicit no.

| family | group | keyboard, canonical | keyboard, transcript | Pointe | LLM router | keyword rules, ours | null (does nothing) |
|---|---|---|---|---|---|---|---|
| twin-symbols | naming | 5/6 | 4/6 | 0/6 | 5/6 | 1/6 | 0/3 |
| homophone-files | naming | 6/6 | 6/6 | 1/6 | 6/6 | 6/6 | 0/3 |
| dictated-literals | naming | 6/6 | 6/6 | 5/6 | 6/6 | 6/6 | 0/3 |
| spelled-out | naming | 6/6 | 4/6 | 4/6 | 6/6 | 3/6 | 0/3 |
| noisy-paths | naming | 6/6 | 6/6 | 0/6 | 5/6 | 4/6 | 0/3 |
| self-correction | language | 6/6 | 6/6 | 3/6 | 6/6 | 3/6 | 0/3 |
| long-dictation | language | 6/6 | 6/6 | 3/6 | 6/6 | 2/6 | 0/3 |
| read-then-decide | language | 6/6 | 6/6 | 1/6 | 6/6 | 6/6 | 0/3 |
| deny-the-decoy | control | 6/6 | 6/6 | 5/6 | 6/6 | 6/6 | 0/3 |
| mid-task-redirect | control | 6/6 | 5/6 | 1/6 | 0/6 | 0/6 | 0/3 |
| two-repo-handoff | control | 6/6 | 6/6 | 1/6 | 4/6 | 5/6 | 0/3 |
| impossible-as-stated | control | 5/6 | 4/6 | 3/6 | 6/6 | 5/6 | 0/3 |
| all 12 families |  | 70/72 | 65/72 | 27/72 | 62/72 | 47/72 | 0/36 |

## The voice gap (synthetic speech)

Keyboard minus the spoken arm, in percentage points, paired by family, with a 95% bootstrap interval over the 12 families. A negative gap means the spoken arm passed more often.

| spoken arm | keyboard, canonical minus it | keyboard, transcript minus it |
|---|---|---|
| Pointe | +60 points (95% CI +43 to +75) | +53 points (95% CI +35 to +69) |
| LLM router | +11 points (95% CI -1 to +31) | +4 points (95% CI -11 to +22) |

Pointe minus the LLM router, paired by family: -49 points (95% CI -65 to -31).

Overall pass rates (runs, not independent; for orientation only): keyboard, canonical 70 of 72, 97% (95% CI 90 to 99%); keyboard, transcript 65 of 72, 90% (95% CI 81 to 95%); Pointe 27 of 72, 38% (95% CI 27 to 49%); LLM router 62 of 72, 86% (95% CI 76 to 92%); keyword rules, ours 47 of 72, 65% (95% CI 54 to 75%); null (does nothing) 0 of 36 (95% upper bound 10%).

## Claims at the end of the task, paired (synthetic speech)

Every task ends with "Is it done, and do the tests pass? Yes or no." False done is a yes on a run that failed, over the failed runs; false not done is a no on a run that passed, over the passed runs. The denominators are small, so this is not a robust number. An answer that cannot be read is no claim.

| arm | false done | false not done | no claim |
|---|---|---|---|
| keyboard, canonical | 2 of 2, 100% (95% CI 34 to 100%) | 9 of 70, 13% (95% CI 7 to 23%) | 0 |
| keyboard, transcript | 6 of 7, 86% (95% CI 49 to 97%) | 10 of 65, 15% (95% CI 9 to 26%) | 0 |
| Pointe | 3 of 45, 7% (95% CI 2 to 18%) | 11 of 27, 41% (95% CI 25 to 59%) | 29 |
| LLM router | 8 of 10, 80% (95% CI 49 to 94%) | 14 of 62, 23% (95% CI 14 to 34%) | 2 |
| keyword rules, ours | 20 of 25, 80% (95% CI 61 to 91%) | 13 of 47, 28% (95% CI 17 to 42%) | 1 |
| null (does nothing) | 0 of 36 (95% upper bound 10%) | n = 0 | 36 |

## Stability, effort, time and spend (synthetic speech)

| arm | pass^2 (items) | flips (items) | clarifications per task | corrective turns per task | time median / p90 | spend per task | capped | invalid (out of tree) | errors | no said after two yeses did not take |
|---|---|---|---|---|---|---|---|---|---|---|
| keyboard, canonical | 34/36 | 2/36 | 0.03 | 0.00 | 32 s / 54 s | $0.003 | 0 | 0 | 0 | 0 |
| keyboard, transcript | 31/36 | 3/36 | 0.06 | 0.00 | 33 s / 54 s | $0.003 | 0 | 0 | 0 | 0 |
| Pointe | 7/36 | 13/36 | 0.08 | 0.47 | 178 s / 256 s | $0.199 | 0 | 0 | 0 | 48 |
| LLM router | 30/36 | 2/36 | 0.03 | 0.03 | 171 s / 314 s | $0.013 | 1 | 0 | 0 | 0 |
| keyword rules, ours | 21/36 | 5/36 | 0.08 | 0.08 | 171 s / 264 s | $0.004 | 0 | 0 | 0 | 0 |
| null (does nothing) | n/a | n/a | 0.00 | 0.92 | 27 s / 32 s | $0.000 | 0 | 0 | 0 | 0 |

pass^2: instances whose two runs both passed. Flips: instances whose two runs disagree. A clarification is a question the item foresaw, answered (no penalty); a corrective turn is a repeated instruction. Capped runs (12 user turns, 10 minutes, or $0.60) count as failures. Invalid runs named a path outside the item's folder in a tool call and are excluded from the passes. Errors are runs the harness could not finish; they count as failures.

Where Pointe lost runs: in 31 of its 45 failed runs at least one spoken yes did not take (Pointe asked for a tap) and the scripted user then said no. That counts runs, not causes. In 22 of those 31 the agent changed no file, so the work stopped at the refusal or after it. In the other 9 the agent had already changed files and the hidden tests still failed. 13 runs passed despite such a refusal. The other arms act on a spoken yes for any command: they have no such guard.

The brain model was slow during the Pointe runs: in 26 of 72 its step passed Pointe's 8 s limit (its fallback's too) and Pointe said "The model took too long to answer"; in the earlier Pointe runs, 3 of 72. Those runs measure the vendor's latency at the time as much as Pointe.

Permission requests Pointe put to the user: 28 read out, which a spoken yes can approve, and 44 tap-only; in the earlier Pointe runs, 9 and 61.

Harness faults: a run in which Claude Code showed a permission prompt without firing its hook, the runner credited an answer to the wrong request, or the agent made no step for 8 minutes was rerun once with the same voice and run index, by that rule and in every arm. Reruns: keyboard, transcript 1, LLM router 1. The first rows stay in the raw data.

## Passes by stressor group (synthetic speech)

| group | keyboard, canonical | keyboard, transcript | Pointe | LLM router | keyword rules, ours | null (does nothing) |
|---|---|---|---|---|---|---|
| naming | 29/30 | 26/30 | 10/30 | 28/30 | 20/30 | 0/15 |
| language | 18/18 | 18/18 | 7/18 | 18/18 | 11/18 | 0/9 |
| control | 23/24 | 21/24 | 10/24 | 16/24 | 16/24 | 0/12 |

## Unpublished seeds, an overfit check (synthetic speech)

One extra seed per family, kept out of the repository (its manifest SHA-256 is in FROZEN.json), one run each. This is not a held-out split: the team that scores its own product holds it, and the generators are public. It only shows whether the results depend on the published seeds.

| arm | passes |
|---|---|
| keyboard, canonical | 12 of 12, 100% (95% CI 76 to 100%) |
| Pointe | 6 of 12, 50% (95% CI 25 to 75%) |

## How it was measured

- One launch line for every arm: interactive claude --model claude-haiku-5-5 --permission-mode acceptEdits in a pseudo-terminal in the task repository, with a fresh CLAUDE_CONFIG_DIR and the API key in its environment only (Bash commands still ask). The Pointe arm adds only --plugin-dir and joins with /pointe:voice. No arm uses claude -p or --bare. A preflight checked that sessions are billed to the API key, load no user plugins and run in acceptEdits.
- Arms: keyboard, canonical (the instruction as a person would type it; approve, deny and Escape as keypresses at the same triggers; the reference ceiling); keyboard, transcript (the exact spoken words, typed: perfect ears); null (starts the sessions, does nothing: the floor); keyword rules, ours (Soniox ears, first word naming a session, yes, no and stop keywords, speaks the agent's final message through local Kokoro); LLM router (Soniox ears, one call per utterance to the brain model of Pointe's default setup with a published 20-line prompt, speech through local Kokoro: the baseline for the head-to-head); Pointe (an isolated daemon in its default setup, audio in over the page's call, audio out recorded).
- Answer keys: hidden tests and the reference patch are written before the session to a folder no arm is given; every config dir denies reads of it and of the bench; every transcript was audited for tool calls naming a path outside the item.
- Scripted user: triggers, slot answers, a question detector (final sentence a question, a wh-word or an auxiliary first, or phrases such as "which one"). On 48 labelled lines rendered by Kokoro and read by Whisper it was right on 48 (100%).
- Item order was shuffled by a recorded seed and the runner went item by item across all arms, so a stop at the budget would have left a random subsample with every arm present.
- Speech: Kokoro-82M v1.0 (Apache-2.0), four voices (US and British, female and male), one seeded voice per instance for both runs; noise made in code (babble from the three other voices at 6 dB for the noisy-paths instruction, pink noise at 12 dB for the rest of that item).

## Run it, add to it

```
uv run --locked --extra local python bench/conversational/hlk/run.py corpus
uv run --locked --extra local python bench/conversational/hlk/run.py verify
uv run --locked --extra local python bench/conversational/hlk/run.py hlk --budget-usd 55 --port-base 9300 --workers 3
```

An adapter implements start, say, type, key, events, speech, versions, spend and stop (bench/conversational/hlk/core/adapter.py); a missing capability shows as coverage, never as a failure. A family is a generator in bench/conversational/hlk/hlk/families/; hlk/CONTRIBUTING.md says how, and run.py verify (free) proves its check goes red and green. Accepted authors are named here. A better router prompt is welcome as a pull request. Family authors so far: the Pointe team.

Spend: $43.11 for HLK in all (smoke and debugging included; cap $55), computed from usage and list prices in bench/conversational/hlk/prices.json. Raw rows and the final files of every published run (run.py verify re-scores them): bench/conversational/hlk/results/. Text and tasks CC BY 4.0, code MIT.
