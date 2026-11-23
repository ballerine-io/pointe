# Spoken Identifiers

**Question:** a spoken instruction names one symbol in a repository full of near twins; does the agent change the
right symbol and nothing else? It complements VoiceCodeBench, which scores recognition, not agent action. The name is
a description, not a brand.

## Dataset

`fixture/` is one invented "almanac" service (Python and TypeScript). `items.toml` lists 55 symbols (one anchor line
each) and **24 targets** in six classes: camelCase against snake_case twins (6), homophones such as cache/cash,
write/right, peak/peek (4), digit forms such as `handler_2`, `sha256`, `v2` (4), dunder and ALL_CAPS names (4), flags
such as `--dry-run`, `--no-verify` (4), nested paths (2). Each target has at least one decoy within edit distance 2 of
its spoken form after normalization (`check.normalize`: case and separators dropped, letters and digits split), which
a test asserts. The action is always the same: a comment that says "marked", directly above the symbol.

Each target is spoken in **2 of the 4 panel voices** by seeded draw, one of the two clips with **12 dB babble** (the
three other panel voices reading filler text): **48 spoken items**. The independent unit is the **target (n = 24)**.
`audio.lock` holds the SHA-256 of every clip; `run.py corpus` rebuilds them.

## Arms

All arms start `claude --model claude-haiku-5-5 --permission-mode acceptEdits` in a pty, with a fresh
`CLAUDE_CONFIG_DIR` and the API key; the Pointe arms add only `--plugin-dir <Pointe at the frozen commit>`.

| Arm | Input | Runs |
|---|---|---|
| keyboard-canonical | the instruction as typed (`parse_moon_phase`) | 24 |
| keyboard-transcript | the exact words the clip was rendered from, typed (perfect ears) | 24 |
| null | starts the session and does nothing (the floor) | 48 |
| naive | Soniox `stt-rt-v6`, then keyword rules; the transcript is typed | 48 |
| llm-router | Soniox `stt-rt-v6`, then one call to Pointe's default brain model with `llm_router_prompt.txt` | 48 |
| pointe | the clip over Pointe's call socket, default setup, isolated daemon | 48 |
| pointe-text | the same words through `POST /voice/say` (separates recognition from the brain) | 24 |

A repeat of 12 seeded spoken items for `pointe` and `llm-router` gives the flip rate.

## Scoring (`check.py`, automatic)

The final repository is compared with the fixture file by file. **right_symbol**: the target is touched (a comment
starting with the word "marked" above its anchor, quotes or backticks around it allowed, or its anchor line changed)
and no other symbol is. **wrong_symbol**: any
other symbol is touched: the harmful outcome, printed beside **no_action** so an arm that does nothing cannot look
safe. **other_change**: something changed but no symbol was touched. `marker_exact` (the comment is exactly
"marked") and `delivered_exact` (the text the harness delivered names the target as it is written) are secondary.
Rows whose transcript names a path outside the item repo are `invalid_out_of_tree` and excluded, with counts.
Each row's log keeps the final text of every file it changed (`final_files`), so `run.py rescore <run-id>` runs the
current `check.py` on the committed results, without the run's `/tmp` folder.

## Choices made here, recorded

- **Shell commands are allowed in every arm's settings.** The design keeps `acceptEdits` with "Bash commands still
  ask". Here the one action is an edit; a shell command the agent picks to look around (for example a `grep` with
  `$(find ...)`) would ask, nobody approves it in this benchmark, and the denied prompt ends the turn. That is noise
  from the agent's tool choice, not from the arm. The permission mode stays `acceptEdits` and is checked per row.
- **The Pointe daemon starts past its first call** (`first-hello` present in its state), as on a Mac that has used
  Pointe; otherwise the first words of every run are taken as the first hello and not acted on.
- **One slot answer.** If the harness or the agent asks a question (the detector in `core/user.py`), the scripted user
  answers once with "I mean <the spoken reference>", in the same voice and noise; it counts as a clarification.
- **No speech out for `naive` and `llm-router`.** No item needs it; their question detection reads the agent's text.
- **Pointe's spend is computed from its log**, with stated assumptions for the tokens it does not log.

## Run record (2026-11-23)

Published summary: `results/identifiers-20261123-031106/summary.json` and `summary.md`, made by
`run.py report identifiers-20261123-031106 llm-router=identifiers-20261123-040357 --why "..."`.

- `FROZEN.json` was committed before the first non-smoke paid row; every row is on Pointe 6544cdc and Claude Code
  2.1.330.
- **llm-router was rerun.** In the first run its call had `max_tokens` 400; `claude-sonnet-5-5` thinks first by
  default, spent the budget, and cut its JSON off, which the adapter read as no action (2 of its first 14 rows,
  reproduced by hand: about one call in two). That handicapped the baseline. The fix (8000, as Pointe's own text calls)
  came after the freeze, with the prompt unchanged; the arm was rerun in full as `identifiers-20261123-040357`. The
  first run's 60 router rows stay committed and are counted as superseded in the summary.
- **The audit was re-run** with one false positive fixed (`"$(git rev-parse --show-toplevel)/almanac/..."` was read as
  an absolute path). `run.py reaudit` reads the transcripts kept in `/tmp/pccb/<run-id>/` and writes `audit.jsonl`;
  the report uses it; the rows are not edited. 3 router rows remain `invalid_out_of_tree` (the agent searched `/`, or
  the item folder, for a misheard name such as `pastMoonPhase`) and are excluded, so the router's n is 45, not 48.
- **Ledger rows of the first run were rebuilt** from its `spend.jsonl` (marked `rebuilt from spend.jsonl`): a
  `git checkout` of the results folder during the run reverted `ledger.jsonl` to its committed state. `spend.jsonl`
  was not affected and holds the same per-run figures.
- **Verification pass (2026-11-23), after the run.** The summary was rebuilt from the committed rows and every
  figure recomputed independently; `check.py` was re-run on every final repository. Changes:
  - **A scorer false negative fixed.** `# \`marked\`` (the word in backticks, directly above `format_equinox_date`)
    was scored `other_change`. The marker rule now allows quotes, backticks or asterisks around the word. One row
    changed: `pointe-text` t06, so `pointe-text` is 24/24, not 23/24, and `pointe-text - pointe` is +17% [+6%, +29%],
    not +12% [-2%, +27%]. `# marked_right_above_parse_moon_phase` (keyboard-transcript t01) still does not count.
  - **The final repositories are committed.** They were only in `/tmp`. `final_files.jsonl` (backfilled by
    `run.py finals` for both runs) rebuilds all 348 rows; under the old rule the rebuilt repositories give every row's
    committed outcome. `rescore.jsonl` is the current check on them, and the report reads it.
  - **`pointe - naive` is in the paired table**: the keyword baseline was nominally the best speech arm.
- The machine was shared with other benchmark runs: the 1-minute load average ranged from about 5 to about 200. No
  metric here is a latency.

## Limits of this run

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
