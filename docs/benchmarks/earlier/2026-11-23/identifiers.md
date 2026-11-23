<!-- The published run of 2026-11-23, before the fixes of what it found (Pointe 6544cdc; barge-in 7113efa). Kept as published; links point at its own files. -->

# Spoken Identifiers

*When a symbol in the repository is spoken, does the agent change the right one and nothing else?*

Part of the [Pointe Conversational Coding Benchmarks](README.md): a self-evaluation with an adapter interface, on synthetic speech. Every reference arm was written by Pointe's team. Every number on this page is computed from the committed results; the Limits section is the benchmark's own README.

## Setup

- Independent unit: target symbol. Sample: 24 targets, each spoken in a clean and a 12 dB babble clip.
- Runs identifiers-20261123-031106, identifiers-20261123-040357 (the LLM router arm rerun in full after a harness fix), 2026-11-23.
- Agent claude-haiku-5-5 in Claude Code 2.1.330, acceptEdits.
- Pointe 6544cdc; one recognizer for every speech arm (soniox:stt-rt-v6).
- LLM router claude-sonnet-5-5; voices af_heart, am_michael, bf_emma, bm_george.

## Results

Outcomes per arm (synthetic speech). The LLM router has 45 valid runs: 3 were excluded for reading outside the repository..

| arm | right symbol | wrong symbol (harmful) | no action |
|---|---|---|---|
| keyboard, canonical | 24/24 = 100% (86-100%) | 0/24 (upper bound 14%) | 0/24 (upper bound 14%) |
| keyboard, transcript | 22/24 = 92% (74-98%) | 1/24 = 4% (1-20%) | 0/24 (upper bound 14%) |
| Pointe | 40/48 = 83% (70-91%) | 2/48 = 4% (1-14%) | 5/48 = 10% (5-22%) |
| Pointe, typed text | 24/24 = 100% (86-100%) | 0/24 (upper bound 14%) | 0/24 (upper bound 14%) |
| LLM router | 39/45 = 87% (74-94%) | 2/45 = 4% (1-15%) | 2/45 = 4% (1-15%) |
| keyword rules, ours | 43/48 = 90% (78-95%) | 2/48 = 4% (1-14%) | 0/48 (upper bound 7%) |
| null (does nothing) | 0/48 (upper bound 7%) | 0/48 (upper bound 7%) | 48/48 = 100% (93-100%) |

- Pointe minus LLM router: -2 points (-10 to +6); Pointe minus keyword rules: -6 points (-17 to +2). No speech arm is measurably better than another.
- Pointe minus keyboard, canonical: -17 points (-29 to -6); Pointe typed minus Pointe spoken: +17 points (+6 to +29). Speech costs Pointe something; its text path does not.
- Pointe right on 22/24 clean clips and 18/24 under 12 dB babble (the clean and babble clips use different voices).
- Flip rate on repeated clips: Pointe 1/12, LLM router 3/12.
- Main failures: the write/right homophone in every speech arm, and misheard words that Pointe and the LLM router rewrote as code names the agent could not find, where keyword rules passed the words as heard.

Full results: [summary.md](../../../../bench/conversational/identifiers/results/identifiers-20261123-031106/summary.md). Raw rows, events and spend: `bench/conversational/identifiers/results/`. Spend on this benchmark, every launch included: $4.88 of a $12 cap, computed from usage and list prices, not a vendor bill.

## Limits

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

Every arm starts the same agent with the same launch line in its own throwaway repository under `/tmp`; an adapter only decides how the words reach it. Details: [the benchmark's README](../../../../bench/conversational/identifiers/identifiers/README.md) and [its harness README](../../../../bench/conversational/identifiers/README.md).
