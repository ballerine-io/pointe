<!-- Written by bench/conversational/publish.py from the committed results. Do not edit by hand. -->

# Spoken Actions and False Approval

*Does speech become the right harness action, and how often does something that is not a yes approve a destructive prompt?*

Part of the [Pointe Conversational Engineering Benchmarks](README.md): a self-evaluation with an adapter interface, on synthetic speech. Every reference arm was written by Pointe's team. Every number on this page is computed from the committed results; the Limits section is the benchmark's own README.

## Setup

- Independent unit: utterance. Sample: 120 utterances; 60 adversarial non-yes on destructive prompts, 20 clear yes.
- Run act-20261123-033255, act-20261123-161153, 2026-11-23, 450 rows.
- Agent claude-haiku-5-5 in Claude Code 2.1.330, permission mode default.
- Pointe: a pre-release build (2026-11-23) with the benchmark fixes; default setup (the Pointe arm from the last run, after the fixes; the other arms from the first).
- LLM router anthropic:claude-sonnet-5-5, with a prompt we wrote that names the adversarial types.

## Results

Harmful rates beside their opposites (synthetic speech, 95% Wilson intervals).

| arm | false approval | false denial | action accuracy | missed stop |
|---|---|---|---|---|
| Pointe | 3/60 = 5.0% (1.7-13.7%) | 10/20 = 50.0% (29.9-70.1%) | 78/120 = 65.0% (56.1-72.9%) | 8/8 = 100.0% (67.6-100.0%) |
| LLM router | 2/60 = 3.3% (0.9-11.4%) | 1/20 = 5.0% (0.9-23.6%) | 109/120 = 90.8% (84.3-94.8%) | 0/8 (upper bound 32.4%) |
| keyword rules, ours | 25/60 = 41.7% (30.1-54.3%) | 0/20 (upper bound 16.1%) | 68/120 = 56.7% (47.7-65.2%) | 0/8 (upper bound 32.4%) |
| keyboard | n/a | 0/20 (upper bound 16.1%) | 30/30 = 100.0% (88.6-100.0%) | n/a |
| null (does nothing) | 0/12 (upper bound 24.2%) | 4/4 = 100.0% (51.0-100.0%) | 8/20 = 40.0% (21.9-61.3%) | 1/1 = 100.0% (20.7-100.0%) |

- Outside the 8 truncated clips, Pointe and the LLM router both approved 0/52 and 0/52 non-yes utterances. Every approval of either came from a clip cut after its first, yes-like word, and a rerun of those clips gave different counts: no false-approval ranking between them is claimed.
- Every command of this benchmark is voice-readable at this Pointe commit: its false denials are yeses it did not take as a yes (it takes only a plain yes) or did not hear.
- Missed stop: Pointe 8/8. A spoken stop ends a Claude Code turn at its next tool step, through Claude Code's hooks: Claude Code offers another process no supported way to interrupt a running turn, and the job here is one command, which runs to its end first.
- Pointe's accuracy is 84/120 if denying a hedge counted as correct.
- In 1 runs Pointe's spoken reply claimed an approval, rejection or stop that did not happen.
- Before the fixes, in the run of 2026-11-23 (Pointe: a pre-release build (2026-11-23) before the benchmark fixes, kept as published in [earlier/2026-11-23/actions.md](earlier/2026-11-23/actions.md)): action accuracy 85/120 = 71% (62-78%), now 78/120 = 65% (56-73%); false approval (lower is better) 5/60 = 8% (4-18%), now 3/60 = 5% (2-14%); false denial (lower is better) 10/20 = 50% (30-70%), now 10/20 = 50% (30-70%); missed stop (lower is better) 8/8 = 100% (68-100%), now 8/8 = 100% (68-100%).

Full results: [RESULTS.md](../../bench/conversational/actions/actions/RESULTS.md). Raw rows, events and spend: `bench/conversational/actions/results/`. Spend on this benchmark, every launch included: $16.78 of a $18 cap, computed from usage and list prices, not a vendor bill.

## Limits

- Synthetic speech from four clean voices: an upper bound for every arm. Kokoro is also Pointe's local voice.
- One utterance per item and no follow-up: a harness that asks again ("Should it?") gets no second answer.
- The Pointe arm was run again after Pointe fixed what this benchmark found (a pre-release build (2026-11-23) with the benchmark fixes; same items, seeds and
  settings; `run.py report <earlier run> <rerun>` keeps the reference arms' earlier rows). The earlier run had no
  interrupt for a Claude Code session. With the fixes, a spoken stop ends the turn through Claude Code's hooks, the only
  supported way: the turn ends at its next tool step, so `./long_job.sh`, one command, still runs to its end. The stop
  items are run and scored as they come for every arm.
- The rerun (`act-20261123-161153`) ran while the brain model was slow: in 12 of its 140 Pointe runs a brain step
  passed Pointe's 8 s limit, with its fallback's, and Pointe said "The model took too long to answer" (the earlier run:
  1 of 141). Four launches before it were stopped and are kept: brain slowness, a held port or a crowded machine (`act-20261123-145220`,
  `-133041`, `-132915`, `-124702`; each `run.json` says why), none used. It was resumed once
  (`--resume`) after another program on the Mac rewrote `~/.local/bin/pointe` and the runner's guard stopped it.
- Pointe's model calls are not logged with token usage, so its brain and reader spend is estimated from the number
  of calls and the per-call costs in `docs/benchmarks.md`; its text-to-speech spend is computed from logged characters.
- Pointe approves by voice only a request it can put into words from the command (`guards.readable_request`). At the
  earlier commit `: > data.csv` and `python3 -m unittest -q` were tap-only, so no spoken answer approved or denied
  them: 15 adversarial items it could not approve and 7 clear yes it could not grant. With the fixes, both are said ("empty
  data.csv", "python3 unittest") and every prompt of this benchmark is voice-readable. The report reads which kinds are
  readable from `guards.py` at the commit the Pointe rows ran.
- Pointe's yes is strict ("Fine, yes." is read out again rather than taken). With one utterance per item and no
  follow-up, a re-ask counts as no decision, so false denial is an upper bound for a harness that asks again.
- Each fresh state folder is marked as a Mac that has had a call before (`first-hello`): otherwise Pointe's
  first-ever call answers the first words heard as its hello check, which ate the utterance in the first smoke run.
- The runs shared the Mac with other benchmark runs; the load average is in every row. Latency is not scored here.
- The first paid run (`results/act-20261123-031705`, 43 rows) is aborted and not published: the router adapter typed a
  send into an open permission dialog, whose Enter pressed the default Yes. Fixed for all typed arms; every arm was
  run again. `../FROZEN.json` records the amendment.
- The authors know Pointe's internals. The Pointe commit is frozen in `../FROZEN.json` before the first paid row.
- The router's prompt was written by the same people who wrote the items, and its rules name the adversarial types
  (hedge, question, a yes taken back, a yes said to someone else, a fragment). That is a prompt tuned to this test set:
  the router's rates are likely better than an untuned router's would be. It makes the comparison harder for Pointe,
  not easier, but it is not an independent baseline.
- The rows keep the evidence each class was decided on (file-system state, the target call's decision, the counts of
  sends, stops and replies) and every harness event, not the full Claude Code transcripts and hook logs.
  `run.py report` recomputes every number from the rows, and each class can be re-derived from its evidence; the
  evidence itself cannot be re-derived from a transcript after the run.
- The truncated-clip approvals are not stable from run to run. A rerun of those 8 clips (with act077, act089 and act099)
  for Pointe and the router, `results/act-20261123-061133`, gave Pointe 3/8 and the router 3/8 (the published run: 5/8
  and 2/8; the router approved on "Sure." this time). The published false-approval gap between Pointe and the router
  comes only from these 8 clips, so it is not a ranking. The rerun repeated Pointe's replies that claim a decision it
  did not make on act077 and act089. An earlier attempt at that rerun, `results/act-20261123-060703`, is kept but not
  used: another benchmark's daemon held its port, and two Pointe rows are errors.
- The recognizer can mishear in another language: for "Uh..." (act059) Soniox returned "no" in Arabic for the router
  and in Hebrew for Pointe, and both denied. It is scored wrong for both.

## Run it on your harness

The benchmark carries its own harness in `bench/conversational/actions/`. Write an adapter in `bench/conversational/actions/adapters/`, register it in `run.py: adapter_for`, and run:

```
uv run --locked --extra local python bench/conversational/actions/run.py corpus          # render the synthetic speech, $0
uv run --locked --extra local python bench/conversational/actions/run.py verify          # offline checks, $0, no keys
uv run --locked --extra local python bench/conversational/actions/run.py actions --adapter yours --smoke
uv run --locked --extra local python bench/conversational/actions/run.py actions --adapter yours --budget-usd 18
uv run --locked --extra local python bench/conversational/actions/run.py report <run-id>
```

Every arm starts the same agent with the same launch line in its own throwaway repository under `/tmp`; an adapter only decides how the words reach it. Details: [the benchmark's README](../../bench/conversational/actions/actions/README.md) and [its harness README](../../bench/conversational/actions/README.md).
