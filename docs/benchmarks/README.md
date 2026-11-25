<!-- Written by bench/publish.py from the release's results. Do not edit by hand. -->

# Pointe 0.8.5, measured

Four benchmarks of Pointe 0.8.5 (commit 756088c7), run on 2026-11-25 against a plain router we wrote as the baseline. Every number on this page is computed from raw rows in the repository; the rows, the commands and the manifest are linked at the end.

- **A self-evaluation.** Pointe's team wrote the benchmarks, the scripted users and the baseline. Nobody outside the team has run them yet.
- **Synthetic or recorded, per row.** Most speech is synthetic (Kokoro and OpenAI voices). Two benchmarks use recorded people: one-word yes and no answers (Speech Commands) and pauses in meetings (AMI).
- **n and spread on every number.** Each benchmark ran more than once; the tables give every run. Intervals are 95%. Where an interval crosses zero, no difference is claimed.
- **Model judges are named.** The only subjective score (naturalness) is two models' reading of transcripts, not people's ratings.

## Headline

| Measure | Pointe 0.8.5 | Plain router | Speech | n and spread |
|---|---|---|---|---|
| First word after you stop speaking, median | 1.9 s (p90 4.5 s) | not comparable (see Baseline) | synthetic | 213 turns, 3 runs; runs: 1.9 s to 2.0 s |
| Turns that got no spoken reply | 4 of 213 | 16 of 213 | synthetic | 3 runs |
| Time to a useful answer, median | 3.3 s (2.6 s to 3.8 s) | 7.2 s (6.3 s to 7.9 s) | synthetic | Pointe minus router: -3.9 s (-4.9 s to -3.2 s): Pointe better |
| Right action | 209 of 232 (84 to 95%) | 183 of 228 (69 to 90%) | synthetic | Pointe minus router: +10 points (-2 points to +23 points): no difference shown |
| Sent to the wrong session / approved what it should not (a no, a hedge, or a yes before the request was read in full) | 2 / 0 | 1 / 3 | synthetic | counts over 3 runs |
| HLK: small coding task finished by voice only | 85 of 105 (72 to 87%) | 93 of 108 (78 to 91%) | synthetic | keyboard 104 of 108; Pointe minus router -5 points (-23 to +15), paired by family |
| Recorded "yes" after a read-out approves | 40 of 40 (91 to 100%) | 38 of 40 (83 to 99%) | recorded people | 20 speakers, 2 runs |
| Recorded "no" after a read-out denies | 40 of 40 (91 to 100%) | 37 of 37 (91 to 100%) | recorded people | 20 speakers, 2 runs |
| Turn taken in the middle of a real pause (Normal, 1.3 s) | 8% (4% to 12%) | not measurable (see Baseline) | recorded people | 171 pauses, 22 speakers not used for tuning |

Intervals are 95%: Wilson for counts, resampling dialogues (or families, or speakers) for the rest.

## Where Pointe loses, and what is not shown

- **No difference shown on:** right action, right session, HLK tasks finished (the interval crosses zero).
- **Pointe is better on:** time to a useful answer, time to a session's answer, words beyond what was needed.
- **Typing still beats Pointe on HLK.** The same tasks typed finish 15 points more often (+0.1 to +33), paired by family: voice costs Pointe tasks.
- **The first word is slow.** A median of 1.9 s and a p90 of 4.5 s after the user stops, against people's gap of about 0.2 s between turns and the 0.6 to 0.8 s that voice-agent vendors aim for ([sources](https://github.com/ballerine-io/pointe/blob/main/bench/conversational/dialogues/RUBRIC.md)).
- **It still cuts people off.** At Normal it takes the turn inside 8% of real mid-sentence pauses of 0.5 s or more, and answers 1.3 s after a real end of turn.
- **Not measured here:** a recorded person saying a whole request, Hebrew spoken by people, a person rating the conversation, any outside product (Codex voice, Happy, Antigravity), or anyone outside the team running this.

## The conversation suite

45 scripted dialogues of one to six turns against real throwaway Claude Code sessions (agent claude-haiku-5-5 in Claude Code 2.1.332), spoken by synthetic voices: four native Kokoro voices, four accented ones, and an OpenAI voice for Hebrew and mixed speech. The scripted user waits for quiet before it speaks and does not adapt. Each dialogue ran on both arms, in one launch, 3 times. Items changed during the quality work before this run, so earlier rounds of the suite are not comparable with these numbers.

| Measure | Pointe 0.8.5, run 1 | Pointe 0.8.5, run 2 | Pointe 0.8.5, run 3 | Plain router, run 1 | Plain router, run 2 | Plain router, run 3 |
|---|---|---|---|---|---|---|
| First word, median | 2.0 s | 1.9 s | 1.9 s | 8.7 s | 9.2 s | 8.5 s |
| First word, p90 | 4.3 s | 5.2 s | 4.3 s | 15.6 s | 16.8 s | 17.0 s |
| Turns with no reply | 1 | 2 | 1 | 5 | 6 | 5 |
| Time to a useful answer, median | 3.0 s | 3.5 s | 3.1 s | 7.2 s | 7.6 s | 6.9 s |
| A session's answer, median | 4.1 s | 3.9 s | 4.2 s | 8.4 s | 8.6 s | 8.1 s |
| Right session | 96% | 96% | 94% | 92% | 92% | 94% |
| Right action | 92% | 91% | 87% | 79% | 80% | 82% |
| Code names exact | 100% | 100% | 100% | 33% | 33% | 33% |
| Hebrew and mixed: right action | 100% | 100% | 100% | 86% | 86% | 86% |
| Words beyond what was needed, median | +6 | +6 | +8 | +14 | +14 | +18 |
| Needless confirmations per 10 turns | 0.3 | 0.3 | 0.6 | 1.3 | 1.5 | 1.0 |
| Naturalness 1 to 5, model judge claude-fable-5-1 | 3.42 | 3.30 | 3.40 | 2.16 | 2.14 | 2.20 |
| Naturalness 1 to 5, model judge gpt-6-sol | 3.27 | 3.13 | 3.09 | 2.09 | 2.11 | 2.22 |

Per run, synthetic speech.

- **First word** is from the end of the user's last voiced frame to the first span of the arm's audio in which a recognizer hears a word; Pointe's waiting sound is not a word, but a word from another session's news is. A turn that got no word counts as the slowest, not left out (an audit found the earlier scorer left it out).
- **Time to a useful answer** is until the turn's goal is met: the expected fact spoken, the request delivered to the right session, or the question asked; a turn whose goal is never met counts as 30 s.
- **Naturalness** is read by two models from a timed transcript with the arm's name removed, one dialogue at a time: Claude Fable (the same vendor as both arms' brain) and OpenAI gpt-6-sol. It is a model's reading, not a person's rating. Judge agreement: Pointe 0.8.5: claude-fable-5-1 vs gpt-6-sol, 134 dialogues, same score 60%, within one point 98%, Spearman 0.786, mean difference +0.22; Plain router: claude-fable-5-1 vs gpt-6-sol, 131 dialogues, same score 67%, within one point 98%, Spearman 0.532, mean difference +0.02.
- **Not published from the suite:** its talk-over, barge-in and backchannel measures (each rests on one or two items, and the router cannot be compared on them), and the composite score of our rubric.

17 dialogue rows were dropped by the rule written before the run (load over 20 at the start or end, or an error) and run again: listed in summary.json.

## Humanity's Last Keystroke (HLK)

36 small coding tasks in 12 families, each finished by voice only and graded by hidden tests on the repository's final state, three runs each. The same agent works in every arm, so a score is what the interface costs, not the agent's strength. Keyboard is the same task typed; Does nothing is the floor. Seeds only change names and numbers, so the sample is close to 12 families, and the intervals are wide.

| Arm | Tasks finished |
|---|---|
| Keyboard | 104 of 108 (91 to 99%) |
| Plain router | 93 of 108 (78 to 91%) |
| Pointe 0.8.5 | 85 of 105 (72 to 87%) |
| Does nothing | 0 of 36 (0 to 10%) |

Synthetic speech, Kokoro voices.

Runs in which the agent wrote outside the task's folder are invalid by HLK's rule and left out of the counts above: Pointe 0.8.5 3. Counted as failures instead: Pointe 0.8.5 85 of 108.

By family, and how each failure happened: [the HLK page](hlk.md).

## Recorded people: yes, no, stop, mm-hm

The one word that answers a permission request is said by a recorded person: 20 speakers of Speech Commands v0.02 (Warden, 2018, CC BY 4.0), one clip each, on their own microphones. The request before it is still a synthetic voice. "Stop" and a listener's "yeah", "okay" or "mm-hmm" over a long answer come from Speech Commands and from the AMI Meeting Corpus (Carletta et al., 2005, CC BY 4.0). The router has no barge-in, so it ran the yes and no dialogues only. The yes and no dialogues ran twice; "stop" and "mm-hm" once.

| Arm, run | "Yes" approved | "No" denied | Approved after a no | "Stop" over an answer: voice stopped after | "Mm-hm" over an answer: stopped the voice |
|---|---|---|---|---|---|
| Pointe 0.8.5, run 1 | 20 of 20 | 20 of 20 | 0 | median 1.3 s, p90 1.7 s (18 of 20 measured) | 1 of 18; sent something 2 |
| Pointe 0.8.5, run 2 | 20 of 20 | 20 of 20 | 0 | n/a | n/a |
| Plain router, run 1 | 19 of 20 | 18 of 18 | 0 | n/a | n/a |
| Plain router, run 2 | 19 of 20 | 19 of 19 | 0 | n/a | n/a |

Recorded people for the one word; synthetic voices for the rest. A yes or no is counted only where the session asked for approval.

Missed: hum-yes-008 (Plain router). Their rows say what was heard.

## Recorded people: when is a turn over?

574 clips of people in AMI meetings, each speaker on their own headset: mid-sentence pauses of 0.5 to 2.0 s, where taking the turn cuts the person off, and real ends of turn, where what counts is how long Pointe waits. Each clip is streamed to Soniox in real time as the daemon does, and the shipped Normal rule (wait 1.3 s after words that read whole) is replayed on what Soniox returned. That rule was tuned on these clips, so the speakers are split in two by a hash of their name: the rule was chosen on one half and the headline is the other half.

| Run and speakers | Speakers | Cut-ins on pauses | Rate (by speaker) | Real end: turn taken after, median / p90 |
|---|---|---|---|---|
| fresh run at 0.8.5: speakers not used for tuning | 22 | 13 of 171 | 8% (4% to 12%) | 1.3 s / 1.3 s |
| fresh run at 0.8.5: speakers used for tuning | 15 | 14 of 120 | 12% (6% to 18%) | 1.3 s / 1.3 s |
| fresh run at 0.8.5: all | 37 | 27 of 291 | 9% (6% to 13%) | 1.3 s / 1.3 s |
| earlier run, same clips, replayed: speakers not used for tuning | 22 | 13 of 168 | 8% (4% to 12%) | 1.3 s / 1.3 s |
| earlier run, same clips, replayed: speakers used for tuning | 15 | 14 of 119 | 12% (6% to 18%) | 1.3 s / 1.3 s |
| earlier run, same clips, replayed: all | 37 | 27 of 287 | 9% (6% to 13%) | 1.3 s / 1.3 s |

Recorded people. Load median 9.4, rows over load 20 dropped: 0.

- These people talk to each other in a meeting, in English, not to a machine and not in Hebrew.
- The ends of turn are followed by digital silence in the corpus copy used, which makes an end easier to detect than on a call.

## The baseline

- **What it is.** The same recognizer as Pointe (Soniox stt-rt-v6), one call per utterance to the same brain model (claude-sonnet-5-5, effort low) with a published prompt, and the same ElevenLabs voice. It reads each permission request aloud and the end of each agent turn. Pointe's team wrote it; a better prompt is welcome.
- **Where it has an edge.** It is handed each utterance whole after it ends, so it never decides when a turn is over and cannot cut anyone off: its turn-taking is not measured, and its times skip the wait Pointe takes before answering (1.3 s at Normal). In HLK its recognizer call is retried on a dropped connection; Pointe's live call is not.
- **Where it is handicapped.** It says nothing until its agent finishes, then reads the agent's last message; it has no memory of sessions beyond names and its last action. Its first-word time measures a different thing from Pointe's, so it is not compared.

## Withdrawn

The five benchmarks published here on 2026-11-23 (HLK, Spoken Identifiers, Spoken Actions, Session Routing, Barge-in) were withdrawn on 2026-11-25 after an integrity audit: they measured a Pointe build that is not public, the reruns heard different audio from the reference arms, the arms ran hours apart, and each had scorer faults (one passed tasks that never reached the agent; one scored a false "approved" as correct; one left unanswered items out of its median). The audit's fixes are in the harness, and the pages are [kept, marked withdrawn](https://github.com/ballerine-io/pointe/tree/main/docs/benchmarks/withdrawn/2026-11-23). HLK was run again for this release.

## Raw results and how to run them

Everything above comes from [the release folder](https://github.com/ballerine-io/pointe/tree/main/bench/results/2026-11-25-v0.8.5) in the repository: the manifest (commits, versions, machine, load, commands), the summary, every row and the spend ledger. Downloads: [manifest.json](https://eng.ballerine.com/pointe/benchmarks/2026-11-25-v0.8.5/manifest.json), [summary.json](https://eng.ballerine.com/pointe/benchmarks/2026-11-25-v0.8.5/summary.json), [all rows, .tar.gz](https://eng.ballerine.com/pointe/benchmarks/2026-11-25-v0.8.5/rows.tar.gz).

```
uv sync --locked --extra local
uv run --locked --extra local python bench/conversational/dialogues/run.py run --arm pointe,llm-router --commit v0.8.5 --workers 3 --port-base 9800 --label rel085-suiteN --budget-usd <ledger total + run>
uv run --locked --extra local python bench/conversational/dialogues/run.py judge <run-id> [--judge openai:gpt-6-sol]
uv run --locked --extra local python bench/conversational/dialogues/run.py run --suite bench/conversational/dialogues/human.toml --arm pointe --commit v0.8.5 --workers 2 --port-base 9888 --label rel085-humanN-pointe
uv run --locked --extra local python bench/conversational/dialogues/run.py run --suite bench/conversational/dialogues/human.toml --arm llm-router --only 'hum-yes-*,hum-no-*' --commit v0.8.5 --workers 2 --port-base 9888 --label rel085-humanN-router
.venv/bin/python -I bench/human_turns.py run --concurrency 2 && .venv/bin/python -I bench/human_turns.py prune --max-load 20 && .venv/bin/python -I bench/human_turns.py run
git worktree add --detach /tmp/pointe-085 v0.8.5 && HLK_POINTE_CHECKOUT=/tmp/pointe-085 uv run --locked --extra local python bench/conversational/hlk/run.py hlk --adapter keyboard-canonical,null,llm-router,pointe --runs 3 --workers 2 --port-base 9300 --budget-usd <ledger total + run>
uv run --locked --extra local python bench/conversational/hlk/run.py report
.venv/bin/python -I bench/release_report.py bench/results/2026-11-25-v0.8.5 && .venv/bin/python -I bench/publish.py bench/results/2026-11-25-v0.8.5
```

Machine: Apple M5 Pro (Mac17,9), 18 cores, 64 GB, macOS 27.0, shared with other work; 1-minute load at each row's start and end is in the rows. Keys come from the macOS Keychain or the environment; the runs call paid APIs.

## Spend

| Benchmark | Spend |
|---|---|
| Conversation suite: 3 runs, both arms, and the reruns the rule required | $25.99 |
| Naturalness judges (Claude Fable and gpt-6-sol) | $4.90 |
| Recorded yes, no, stop and mm-hm, with reruns | $24.21 |
| HLK: smoke and the run | $28.48 |
| End of turn on recorded pauses (Soniox, computed from seconds streamed) | $0.28 |
| Smoke of the suite | $0.15 |
| All | $84.01 |

Computed from usage and list prices, not metered; smoke runs and reruns included.

The speech components (recognizers, brains, voices) were benchmarked one at a time, on synthetic speech, before 0.8.5: [speech component benchmarks](https://eng.ballerine.com/pointe/docs/benchmarks/).
