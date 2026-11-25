# Session Routing (`routing`)

**Question:** with four live Claude Code sessions, does a spoken request reach the right one, and does an ambiguous
request cause a question instead of a guess? We found no published benchmark for this.

Part of the Pointe Voice Coding Benchmarks (design: section 5.4). Synthetic speech only. Every arm,
baselines included, was written by the team whose product is under test.

## Run

```
uv sync --locked --extra local                                       # Kokoro and the local models, once
uv run --locked python bench/conversational/routing/run.py corpus            # render the 204 clips, $0
uv run --locked python bench/conversational/routing/run.py routing --budget-usd 9 --dry-run
uv run --locked python bench/conversational/routing/run.py routing --budget-usd 9 [--adapter pointe,llm-router] [--smoke]
uv run --locked python bench/conversational/routing/run.py report <run-id>   # rows -> RESULTS.md and results.json
uv run --locked pytest -q tests/test_conversational_bench.py         # offline, no keys
```

Keys: the agents read the Anthropic key through `apiKeyHelper` (Keychain item `pointe.anthropic-api-key` or
`anthropic-api-key`); the router and the baseline ears read the Anthropic and Soniox keys into the runner process
only; the Pointe daemon reads its own keys as it always does. No key is put in a file, an argument or the
environment of another process.

## Dataset

Four throwaway repos made per conversation by `fixture/make.py`: `tariff` (a backend API), `tariff-web` (its web
front end), `depot` (another backend API), `depot-docs` (its documentation). Names checked against Pointe's own tests
(`tests/test_conversational_bench.py` fails on a collision). Each repo has a private marker file.

`conversations.toml`: 12 conversations x 5 turns = 60 turns, one Kokoro voice per conversation (af_heart, am_michael,
bf_emma, bm_george, three conversations each). Every turn asks for a one-line edit carrying a unique word, so the file
system shows where it went.

| Type | n | Example |
|---|---|---|
| by name | 16 | "In tariff web, add a line with the word candle to the notes file." |
| by description | 10 | "In the web front end, ..." |
| by context | 10 | "Same one again: ...", "Now the other tariff one: ...", "Back to the one before that: ..." |
| ambiguous on purpose | 14 | "In the tariff one, ..." (tariff or tariff-web), "In the backend, ..." (tariff or depot) |
| two sessions at once | 5 | "... in both tariff and depot docs." |
| easy to mishear | 5 | name first, clipped, rendered at Kokoro speed 1.3: "Depot docs: add ... to notes." |

Every reference is resolved by `check.resolve`; the offline test asserts each stored target equals the resolution,
that every ambiguous turn resolves to exactly two sessions, and that the turn before it does not decide it.

## Arms

All arms start the same four sessions the same way: interactive `claude --model claude-haiku-5-5 --permission-mode
acceptEdits` in a pty, in its own `/tmp` repo, with a fresh `CLAUDE_CONFIG_DIR`. Pointe adds only `--plugin-dir`.
The runner asserts four live processes in four distinct `/tmp` working folders, and no process left at the end.

| Arm | What it is |
|---|---|
| `pointe` | Pointe at the frozen commit on an isolated daemon (state under `/tmp`, ports 9610/9611), sessions joined with `/pointe:voice`, the e2e rig's fake page playing the audio. Setup resolved from the keys present and recorded. Starts set up (the `setup-done` and `first-hello` markers), not on its first-ever call. |
| `llm-router` | Same audio, Pointe's default recognizer (Soniox real-time, biased with the four session names as Pointe biases its own), one call per utterance to the brain model Pointe resolves to, prompt in `adapters/llm_router_prompt.txt`, Pointe's default brain effort (`low`). The baseline for any comparison. |
| `naive` | "Keyword rules, ours": the first word that matches a session name picks it, else the session used last; never asks. Same transcripts as `llm-router`. Never in a headline delta. |
| `keyboard-canonical` | A seeded 20 of the 46 clear turns, typed into the named session: the agent's own failure rate on the edit. No routing. |
| `null` | Starts the sessions and does nothing: the floor. |

A seeded repeat of 3 conversations for `pointe` and `llm-router` gives the flip rate.

## Scoring (automatic, from the file system)

- **Routing accuracy:** the turn's word ends up in exactly the intended repos. On an ambiguous turn the arm must also
  ask before anything is delivered; the intended repo is the one the scripted user names when asked.
- **Wrong-session delivery** (the harmful outcome): the arm sent the request to a session it was not meant for, or the
  word appeared in such a repo. An agent that receives a misrouted request and refuses it still counts.
- **Ask rate on the 14 ambiguous turns beside the ask rate on the 46 clear turns**, on one row, with raw counts.
- Conversation success (all five turns right), clarifications, generic replies, by-type counts, flip rate.
- Wilson 95% intervals on turns, a bootstrap by conversation (n = 12), the `null` floor row, n in every table.

The scripted user (`core/user.py`) answers a question that offers sessions or asks which with the turn's answer line,
a confirmation that names exactly the intended sessions with "Yes, go ahead.", one that names another session with
"No, ...", and anything else with "Please go on with what I asked." Before anything is delivered every question is
answered; after a delivery, only on a two-session turn delivered in part. A permission read-out is never answered. At
most two replies per turn. It waits for Pointe's speech to finish before it talks.

Every session's settings (the same file in every arm) deny Read, Edit and Write on the other three repos, and a
permission dialog left open for 5 s is answered as a person at the keyboard would, and recorded: approved
(`prompt_approved`) when every path it names is inside the session's own repo, declined with Escape
(`prompt_declined`) otherwise. Without this, a misrouted agent that reached into a sibling repo held its dialog open
until the turn's cap and swallowed the next request.

## Deviations from the design, stated

- **Questions are detected from each arm's own text** (Pointe's `speak:` log line, the router's question), not from a
  recognizer run on recorded audio. Routing is scored on the file system; the question only decides the ask rate,
  and the exact text is the more reliable input for every arm alike. The detector is tested on 40 labelled lines.
- **Baseline speech out is not rendered.** Nothing in this benchmark scores it.
- **Out-of-tree reads:** a turn is excluded only when an agent's tool call names the checkout's benchmark folder
  (the answer keys). A read into a sibling repo of the run is counted per arm and kept: it happens after the arm has
  routed the request (after a misroute the agent looks for the repo it was meant for), edits there are denied, and
  excluding those turns would drop mostly the failures of the arm that misroutes (in the paid run, all 14 such turns
  were naive's). `find /` and `find ~` are denied in every arm's settings (the same file everywhere).
- **Spend is computed, not metered:** agents from transcript usage, the router from response usage, Soniox from audio
  seconds, Pointe's vendors from its log with stated assumptions (reply tokens per brain step, a reader report per
  finished turn, a checker call per send). See `prices.json`.

## Limits

Synthetic speech from one engine that is also Pointe's own local voice: an upper bound for everyone. n = 12
conversations; intervals are wide and close systems cannot be ranked. The ambiguous turns are ambiguous by a stated
construction (two sessions share the product word or the role); a reader may judge some of them differently. One
laptop under load from other work (load average in every row). Haiku as the fixed agent.

Found in an adversarial check of the first published run, stated here so the numbers are read correctly:

- **The rerun after the fixes** (`routing-20261123-1246-a9f2`, a pre-release build (2026-11-23) with the benchmark fixes, Pointe arm only, same conversations,
  seeds and settings; `run.py report routing-20261123-0331-d17a routing-20261123-1246-a9f2` takes each arm from the last
  run that ran it). No send delivered an earlier request's text. One conversation (c12) timed out at the start on a
  loaded machine and was run again with `--resume`; the first attempt wrote no turn rows (its events and spend are kept). The bullets below
  describe the earlier run, kept as published in `RESULTS-2026-11-23-before-fixes.md`.
- **The sentence template amplified Pointe's main failure in the earlier run.** Every request is "add a line with the
  word X to the notes file" with one word changed. In the earlier frozen build, before the fixes, Pointe's send layer, when the user's words name a session, can
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
