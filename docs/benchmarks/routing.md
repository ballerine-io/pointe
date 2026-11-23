<!-- Written by bench/conversational/publish.py from the committed results. Do not edit by hand. -->

# Session Routing

*With four live sessions, does a spoken request reach the right one, and is an ambiguous one asked about?*

Part of the [Pointe Conversational Engineering Benchmarks](README.md): a self-evaluation with an adapter interface, on synthetic speech. Every reference arm was written by Pointe's team. Every number on this page is computed from the committed results; the Limits section is the benchmark's own README.

## Setup

- Independent unit: conversation. Sample: 12 conversations of 5 turns (60 turns).
- Run routing-20261123-0331-d17a, routing-20261123-1246-a9f2, 2026-11-23.
- Agent claude-haiku-5-5 in Claude Code 2.1.330, acceptEdits.
- Pointe 84eafbc: brain anthropic:claude-sonnet-5-5, ears soniox, mouth elevenlabs:eleven_v4_turbo.
- LLM router claude-sonnet-5-5 at effort low; ears soniox:stt-rt-v6.

## Results

Routing per turn (synthetic speech, 95% Wilson intervals).

| arm | routed right | wrong session | asked first: ambiguous vs clear turns | conversations all right |
|---|---|---|---|---|
| Pointe | 49/60 = 82% (70-89%) | 7/60 = 12% (6-22%) | 4/14 vs 3/46 | 4/12 |
| LLM router | 55/60 = 92% (82-96%) | 3/60 = 5% (2-14%) | 10/14 vs 2/46 | 8/12 |
| keyword rules, ours | 27/60 = 45% (33-58%) | 22/60 = 37% (26-49%) | 0/14 vs 0/46 | 0/12 |
| keyboard, canonical | 19/20 = 95% (76-99%) | 0/20 (upper bound 16%) | 0/0 vs 0/20 | n/a |
| null (does nothing) | 0/60 (upper bound 6%) | 0/60 (upper bound 6%) | 0/14 vs 0/46 | 0/12 |

- Pointe minus LLM router, paired by turn: -10 points (-18 to -2) (bootstrap by conversation).
- No send delivered an earlier request's text (0 of Pointe's 11 failed turns; the earlier run lost 9 turns that way). Pointe's remaining failures are ambiguous turns where it guessed instead of asking: it asked first on 4 of 14.
- Flip rate on 3 repeated conversations: Pointe 3/15, LLM router 1/15 (not like for like: the router reuses cached transcripts).
- Before the fixes, in the run of 2026-11-23 (Pointe 6544cdc, kept as published in [earlier/2026-11-23/routing.md](earlier/2026-11-23/routing.md)): turns routed right 41/60 = 68% (56-79%), now 49/60 = 82% (70-89%).

Full results: [RESULTS.md](../../bench/conversational/routing/routing/RESULTS.md). Raw rows, events and spend: `bench/conversational/routing/results/`. Spend on this benchmark, every launch included: $10.17 of a $11 cap, computed from usage and list prices, not a vendor bill.

## Limits

Synthetic speech from one engine that is also Pointe's own local voice: an upper bound for everyone. n = 12
conversations; intervals are wide and close systems cannot be ranked. The ambiguous turns are ambiguous by a stated
construction (two sessions share the product word or the role); a reader may judge some of them differently. One
laptop under load from other work (load average in every row). Haiku as the fixed agent.

Found in an adversarial check of the first published run, stated here so the numbers are read correctly:

- **The rerun after the fixes** (`routing-20261123-1246-a9f2`, Pointe 84eafbc, Pointe arm only, same conversations,
  seeds and settings; `run.py report routing-20261123-0331-d17a routing-20261123-1246-a9f2` takes each arm from the last
  run that ran it). No send delivered an earlier request's text. One conversation (c12) timed out at the start on a
  loaded machine and was run again with `--resume`; the first attempt wrote no turn rows (its events and spend are kept). The bullets below
  describe the earlier run, kept as published in `RESULTS-2026-11-23-pointe-6544cdc.md`.
- **The sentence template amplified Pointe's main failure in the earlier run.** Every request is "add a line with the
  word X to the notes file" with one word changed. At the earlier frozen commit (6544cdc) Pointe's send layer, when the user's words name a session, can
  replace the brain's message with an earlier request's text if the two share at least half their content words
  (`_corrects_last_send`, `_mostly_same`). With this template every pair of requests qualifies, so the swap fired in 9
  of Pointe's 19 failed turns, 7 of them right after it asked which session; in all 9 the brain's own call carried the
  right word and session (RESULTS.md, read from the committed daemon logs). The defect is real, but varied speech would
  trigger it far less often, so the Pointe minus llm-router gap here overstates the gap to expect in use.
- **The llm-router prompt was written by people who knew the dataset**, and it states the dataset's own ambiguity rule
  ("names that share a word are different sessions"; "if two or more sessions fit ... ask"). Pointe's brain prompt was
  not written for this benchmark. The router sees only the four session names, not the repos.
- **10 of the 14 ambiguous turns have the same form**, "in the tariff one" or "in the depot one", where one session
  carries exactly that name. A reader may judge that form as naming that session. llm-router lost 4 such turns by
  picking that session without asking, Pointe 6 (of its 7 guesses).
- **A context turn after an ambiguous turn can be penalised twice.** "Same one again" after an unasked ambiguous turn
  is scored against the session the user meant, not the one the arm announced (c09, turn 4: both pointe and llm-router).
- **The flip rate is not like for like.** The baselines' transcripts are cached per clip, so the llm-router repeat has
  no recognizer variance; Pointe hears every repeat live.
- **The scripted user answers questions only.** When Pointe said "Please say it again" (an instruction, c01 turn 5), it
  did not repeat, and the turn was missed.
- **Three earlier paid runs were stopped after one conversation (c12)** for harness defects that applied to every arm
  (`routing-20261123-0257-c83e`, `-0312-e0ec`, `-0324-0e67`; the reason is in each `run.json`). Their rows are committed
  and used in no table. Total spend on this benchmark, smoke and stopped runs included, is in `results/ledger.jsonl`.
- **A sample re-run** (`routing-20261123-0435-4aeb-verify`, `rerun_sample.py c06,c12`, same frozen commit): pointe 8/10,
  llm-router 10/10, against 7/10 and 10/10 for the same conversations in the published run. This time Pointe guessed on
  both ambiguous turns of c06 instead of asking, and no send was replaced: the swap follows a question. Used in no table.

Licenses: text CC BY 4.0, code MIT, audio rendered by Kokoro-82M (Apache-2.0). Canary: `../CANARY`.

## Run it on your harness

The benchmark carries its own harness in `bench/conversational/routing/`. Write an adapter in `bench/conversational/routing/adapters/`, register it in `run.py: make_arm`, and run:

```
uv run --locked --extra local python bench/conversational/routing/run.py corpus          # render the synthetic speech, $0
uv run --locked --extra local python bench/conversational/routing/run.py verify          # offline checks, $0, no keys
uv run --locked --extra local python bench/conversational/routing/run.py routing --adapter yours --smoke
uv run --locked --extra local python bench/conversational/routing/run.py routing --adapter yours --budget-usd 11
uv run --locked --extra local python bench/conversational/routing/run.py report <run-id>
```

Every arm starts the same agent with the same launch line in its own throwaway repository under `/tmp`; an adapter only decides how the words reach it. Details: [the benchmark's README](../../bench/conversational/routing/routing/README.md) and [its harness README](../../bench/conversational/routing/README.md).
