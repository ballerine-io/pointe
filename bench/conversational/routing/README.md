# Session Routing (`routing`)

**Question:** with four live Claude Code sessions, does a spoken request reach the right one, and does an ambiguous
request cause a question instead of a guess? We found no published benchmark for this.

Part of the Pointe Conversational Coding Benchmarks (design: section 5.4). Synthetic speech only. Every arm,
baselines included, was written by the team whose product is under test.

## Run

```
uv sync --locked --extra local                                       # Kokoro and the local models, once
uv run --locked python bench/conversational/run.py corpus            # render the 204 clips, $0
uv run --locked python bench/conversational/run.py routing --budget-usd 9 --dry-run
uv run --locked python bench/conversational/run.py routing --budget-usd 9 [--adapter pointe,llm-router] [--smoke]
uv run --locked python bench/conversational/run.py report <run-id>   # rows -> RESULTS.md and results.json
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
a question that names exactly the intended sessions with "Yes, go ahead.", one that names another session with
"No, ...", and anything else with "Please go on with what I asked." At most two replies per turn. It waits for
Pointe's speech to finish before it talks.

## Deviations from the design, stated

- **Questions are detected from each arm's own text** (Pointe's `speak:` log line, the router's question), not from a
  recognizer run on recorded audio. Routing is scored on the file system; the question only decides the ask rate,
  and the exact text is the more reliable input for every arm alike. The detector is tested on 40 labelled lines.
- **Baseline speech out is not rendered.** Nothing in this benchmark scores it.
- **Out-of-tree reads:** a turn is excluded only when an agent's tool call names the checkout's benchmark folder or
  another repo of this run (a read that could change a score). Other paths outside the repo (a system file) are
  counted per row and kept. `find /` and `find ~` are denied in every arm's settings (the same file everywhere): on
  a misrouted request the agent otherwise searched the disk and stalled the turn.
- **Spend is computed, not metered:** agents from transcript usage, the router from response usage, Soniox from audio
  seconds, Pointe's vendors from its log with stated assumptions (reply tokens per brain step, a reader report per
  finished turn, a checker call per send). See `prices.json`.

## Limits

Synthetic speech from one engine that is also Pointe's own local voice: an upper bound for everyone. n = 12
conversations; intervals are wide and close systems cannot be ranked. The ambiguous turns are ambiguous by a stated
construction (two sessions share the product word or the role); a reader may judge some of them differently. One
laptop under load from other work (load average in every row). Haiku as the fixed agent.

Licenses: text CC BY 4.0, code MIT, audio rendered by Kokoro-82M (Apache-2.0). Canary: `../CANARY`.
