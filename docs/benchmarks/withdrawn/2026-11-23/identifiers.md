<!-- Written by bench/conversational/publish.py from the committed results. Do not edit by hand. -->

> **Withdrawn on 2026-11-25.** This page reports a run of 2026-11-23 on a Pointe build that is not public
> (`84eafbc`, and `6544cdc` before the fixes). An integrity audit found faults that change its numbers: the measured
> builds cannot be checked out, the "after" reruns heard different audio from the reference arms, the arms ran hours
> apart, runs were stopped without a rule written first, and each benchmark has scorer faults of its own (HLK passed
> tasks that never reached the agent and named its trap items in the agent's folder; Spoken Actions scored a false
> "approved" as correct; Barge-in left unanswered items out of its median; Routing's baseline prompt restated the
> dataset's rules; Identifiers was tuned on its own test items). It is kept as it was published, for the record. Do not
> cite its numbers. The current results: [docs/benchmarks/README.md](../../README.md).


# Spoken Identifiers

*When a symbol in the repository is spoken, does the agent change the right one and nothing else?*

Part of the [Pointe Conversational Engineering Benchmarks](README.md): a self-evaluation with an adapter interface, on synthetic speech. Every reference arm was written by Pointe's team. Every number on this page is computed from the committed results; the Limits section is the benchmark's own README.

## Setup

- Independent unit: target symbol. Sample: 24 targets, each spoken in a clean and a 12 dB babble clip.
- Runs identifiers-20261123-031106, identifiers-20261123-040357, identifiers-20261123-125649: the Pointe arms from the last, run after the fixes; the LLM router from the second (rerun in full after a harness fix); the other arms from the first. 2026-11-23.
- Agent claude-haiku-5-5 in Claude Code 2.1.330, acceptEdits.
- Pointe: a pre-release build (2026-11-23) with the benchmark fixes; one recognizer for every speech arm (soniox:stt-rt-v6).
- LLM router claude-sonnet-5-5; voices af_heart, am_michael, bf_emma, bm_george.

## Results

Outcomes per arm (synthetic speech). The LLM router has 45 valid runs: 3 were excluded for reading outside the repository..

| arm | right symbol | wrong symbol (harmful) | no action |
|---|---|---|---|
| keyboard, canonical | 24/24 = 100% (86-100%) | 0/24 (upper bound 14%) | 0/24 (upper bound 14%) |
| keyboard, transcript | 22/24 = 92% (74-98%) | 1/24 = 4% (1-20%) | 0/24 (upper bound 14%) |
| Pointe | 42/48 = 88% (75-94%) | 2/48 = 4% (1-14%) | 3/48 = 6% (2-17%) |
| Pointe, typed text | 23/24 = 96% (80-99%) | 0/24 (upper bound 14%) | 0/24 (upper bound 14%) |
| LLM router | 39/45 = 87% (74-94%) | 2/45 = 4% (1-15%) | 2/45 = 4% (1-15%) |
| keyword rules, ours | 43/48 = 90% (78-95%) | 2/48 = 4% (1-14%) | 0/48 (upper bound 7%) |
| null (does nothing) | 0/48 (upper bound 7%) | 0/48 (upper bound 7%) | 48/48 = 100% (93-100%) |

- Pointe minus LLM router: +2 points (-12 to +15); Pointe minus keyword rules: -2 points (-10 to +4). No speech arm is measurably better than another.
- Pointe minus keyboard, canonical: -12 points (-25 to -2); Pointe typed minus Pointe spoken: +8 points (-6 to +23). Speech costs Pointe something; its text path does not.
- Pointe right on 20/24 clean clips and 22/24 under 12 dB babble (the clean and babble clips use different voices).
- Flip rate on repeated clips: Pointe 0/12, LLM router 3/12.
- The write/right homophone (t08) is still wrong for Pointe: the recognizer hears the name as "right column" and the agent picks right_column although Pointe now says what the hint means. Code names built from misheard words now go to the agent with the words as heard; no Pointe row failed that way in this run.
- Two of Pointe's three no-action rows are one target (t07) whose speech never reached Pointe: the recognizer's connection dropped on a loaded machine (load average up to 517 during the run). They are counted as they came.
- Before the fixes, in the run of 2026-11-23 (Pointe: a pre-release build (2026-11-23) before the benchmark fixes, kept as published in [earlier/2026-11-23/identifiers.md](earlier/2026-11-23/identifiers.md)): right symbol 40/48 = 83% (70-91%), now 42/48 = 88% (75-94%).

Full results: [summary.md](../../bench/conversational/identifiers/results/identifiers-20261123-125649/summary.md). Raw rows, events and spend: `bench/conversational/identifiers/results/`. Spend on this benchmark, every launch included: $8.09 of a $12 cap, computed from usage and list prices, not a vendor bill.

## Limits

- **The Pointe arms were run again after the fixes** (`identifiers-20261123-125649`, a pre-release build (2026-11-23) with the benchmark fixes, the same clips,
  voices and settings; `run.py report identifiers-20261123-125649 <arm>=<earlier run> ...` takes the other arms from
  the earlier runs). With the fixes, a code name the brain builds from the user's words goes to the agent with the words as
  heard, and "X, as in Y" for a homophone is resolved in code (`relay.py`). The bullets below on code names, the marker
  text, noise and timing describe the earlier run (`identifiers-20261123-031106`, its own `summary.md`). In the rerun,
  Pointe's no-action rows are t07 twice (the recognizer's connection dropped on a loaded machine, load average up to
  517, so no words reached Pointe) and t21 once (the recognizer gave Pointe only the last words, "Time zone."); t08,
  the homophone, is still wrong twice: the name itself is heard as "right column".
- **Small.** 24 targets in one invented repository, one agent model (`claude-haiku-5-5`). A difference under about
  ten points between two speech arms is not resolved: every speech-arm interval overlaps.
- **One recognizer.** `pointe`, `llm-router` and `naive` all hear through Soniox `stt-rt-v6`, and on the same clip they
  mostly got the same transcript. The comparison is what each does with the words, not how well it hears.
- **Misheard words written as code names.** When Soniox heard "past moon phase" or "get tied table", `pointe` and
  `llm-router` wrote it as a code name (`pastMoonPhase`, `getTiedTable`), the agent found no such name and changed
  nothing. `naive` typed the words as heard and the agent matched `parseMoonPhase` and `getTideTable`. This, and the
  write/right homophone (t08, wrong in every speech arm), are most of the speech arms' failures.
- **Helpful scripts.** The spoken forms carry hints a person may not give ("write as in writing", "in snake case").
- **The marker text counts.** Six rows found the target but wrote another comment or put it inside the function
  (`pointe` 1, `llm-router` 2, `naive` 2, `keyboard-transcript` 1). Counted as right, `pointe - llm-router` is -4%
  [-10%, 0%], not -2% [-10%, +6%].
- **Exclusions.** 3 `llm-router` rows are `invalid_out_of_tree` (2 right, 1 no action); at their check outcome the arm
  is 41/48. The audit reads absolute paths only: one `llm-router` row of the rerun listed its item folder with
  `ls -la ..` (it changed nothing and is counted).
- **Noise.** `pointe` falls from 22/24 clean to 18/24 under babble (paired by target -17% [-33%, -4%]); `naive` and
  `llm-router` do not fall. A target's clean and babble clips are in different voices.
- **Timing.** The `llm-router` rerun ran after the other arms (04:04 to 04:16); the machine's load varied from about 5
  to about 200. No metric is a latency.

## Run it on your harness

The benchmark carries its own harness in `bench/conversational/identifiers/`. Write an adapter in `bench/conversational/identifiers/adapters/`, register it in `identifiers/bench.py: make_adapter`, and run:

```
uv run --locked --extra local python bench/conversational/identifiers/run.py corpus          # render the synthetic speech, $0
uv run --locked --extra local python bench/conversational/identifiers/run.py verify          # offline checks, $0, no keys
uv run --locked --extra local python bench/conversational/identifiers/run.py identifiers --adapter yours --smoke
uv run --locked --extra local python bench/conversational/identifiers/run.py identifiers --adapter yours --budget-usd 12
uv run --locked --extra local python bench/conversational/identifiers/run.py report <run-id>
```

Every arm starts the same agent with the same launch line in its own throwaway repository under `/tmp`; an adapter only decides how the words reach it. Details: [the benchmark's README](../../bench/conversational/identifiers/identifiers/README.md) and [its harness README](../../bench/conversational/identifiers/README.md).
