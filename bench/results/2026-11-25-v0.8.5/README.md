# Pointe 0.8.5, measured on 2026-11-25

The rows behind every number on [docs/benchmarks/README.md](../../../docs/benchmarks/README.md) and the site's
benchmark page. Nothing here is edited by hand except `manifest.json`, which names the runs.

| File | What it is |
|---|---|
| `manifest.json` | The release and its commit, the agent, the machine, every run id, the commands, the spend |
| `summary.json` | Every published number, written by `bench/release_report.py` from the files below |
| `dialogues/<run-id>/rows.jsonl` | The conversation suite and the recorded yes/no/stop/mm-hm dialogues: one row per dialogue and arm, with the user's turns, what the arm said (as a recognizer heard it, with times), what each session received, its hook events and the files it changed |
| `dialogues/<run-id>/judge-<arm>*.json` | The naturalness scores of each model judge, with its two-sentence reason |
| `dialogues/<run-id>/run.json` | The run's arms, dialogues, Pointe commit and start time |
| `ledger.jsonl` | Spend and machine load of every dialogue row (start and end), copied from the suite's ledger |
| `turn-human.jsonl` | The end-of-turn run on recorded people: what Soniox returned for each AMI clip, with times |
| HLK | Its rows stay with its harness: `bench/conversational/hlk/results/<run-id>/` |

Rules written before the rows were read (also in `bench/release_report.py`):

- A dialogue row counts only if the 1-minute load was at most 20 at its start and its end and it has no error. A
  dropped row is listed in `summary.json` and its dialogue is run again in a separate run id.
- Each run is scored on its own. Intervals are 95%: resampling dialogues (all runs of a dialogue together), families
  (HLK) or speakers (end of turn), 2,000 times with a fixed seed; Wilson for counts.
- A turn that got no spoken reply counts as the slowest first word.

Recompute: `.venv/bin/python -I bench/release_report.py bench/results/2026-11-25-v0.8.5`, then
`.venv/bin/python -I bench/publish.py bench/results/2026-11-25-v0.8.5`.

Licences: the Speech Commands clips (Warden, 2018) and the AMI Meeting Corpus (Carletta et al., 2005) are CC BY 4.0;
their words appear in these rows under that licence. The synthetic speech is Kokoro-82M (Apache-2.0) and OpenAI
`gpt-4o-mini-tts`.
