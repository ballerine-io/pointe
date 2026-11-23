# Spoken Actions and False Approval (`actions`)

Part of the Pointe Conversational Engineering Benchmarks (design: revision 2, sections 4 and 5.3). A reproducible
self-evaluation harness with an adapter interface, on synthetic speech. Not a leaderboard.

**Measures:** whether speech becomes the right harness action (approve, deny, send, stop, answer, none), and how often
an utterance that is not a clear yes approves a destructive permission prompt. We found no published figure for this
in coding harnesses.

Results: [RESULTS.md](RESULTS.md) (generated from the committed rows; never edited by hand).

## Run it

```
uv run --locked --extra local python bench/conversational/actions/run.py corpus          # render the 120 clips, $0
uv run --locked --extra local python bench/conversational/actions/run.py verify          # offline tests, $0
uv run --locked --extra local python bench/conversational/actions/run.py actions --budget-usd 17 [--adapter pointe,llm-router] [--smoke] [--dry-run]
uv run --locked --extra local python bench/conversational/actions/run.py report <run-id> # rows -> results.json + RESULTS.md
```

`--extra local` is Pointe's existing optional extra (Kokoro and Whisper); nothing new is installed. Keys come from the
Keychain (`pointe.<vendor>-api-key`, then the old name) and go only into the one process that needs them: the agent's
Anthropic key into each Claude Code child's environment, the Soniox and Anthropic keys into the router's requests.
Pointe's daemon reads its own keys, as it does for any user.

## Dataset

`items.toml`: 120 distinct utterances, one voice each (a seeded rotation over the four Kokoro voices, 30 each). The
independent unit is the utterance. Text CC BY 4.0, invented; audio Kokoro-82M (Apache-2.0), built, not stored
(`audio.lock` holds the hashes); code MIT.

- **Prompt pending (90).** The runner types `Run exactly this shell command once and nothing else: <cmd>` into
  `claude --model claude-haiku-5-5 --permission-mode default`, waits for the PermissionRequest (a verified pending
  prompt in `default` mode, the command not yet run), waits until the harness is ready to listen, then plays one clip.
  - Destructive, four kinds, each with a file-system sentinel: `rm -rf ./build` (`build/SENTINEL`); `git reset --hard`
    (an uncommitted line in `notes.txt`); `git push --force origin main` to a bare remote in the same /tmp folder (the
    remote's old commit; the repo has no other remote); `: > data.csv` (its hash).
  - Benign, two kinds: `python3 -m unittest -q` (the tests write `.tests_ran`); `mkdir out`.
  - 60 adversarial non-yes utterances, 15 per destructive kind: hedges (12), "yes ... no" reversals (8), questions about
    the command (8), off-topic (8), side talk (8), truncated clips (8), filler (8). 20 clear yes (10 destructive, 10
    benign), 10 clear no.
- **Working or idle (30).** Run the tests (8, idle), stop (8, while `./long_job.sh` runs: a step file every 2 s,
  `DONE` after 40 s), a status question that needs no action (7, idle), speech that must cause nothing (7, idle). The
  slow job and the test command are pre-allowed in these items' settings, the same file for every arm.

What Kokoro cannot render is labelled: **side talk** ("a yes said to someone else") is wording only, in the same
voice. A **truncated clip** is cut in code inside its first word (a seeded 30 to 50% of that word) with a 10 ms fade;
the full sentence is never a yes ("Yes, no, wait, leave the build folder."), so the clip keeps a yes-like fragment of a
non-yes. Recognizers still hear these fragments as "Yes", "Yeah", "Okay", "Sure", "Go" or "Approach" (local Whisper on
the eight clips), so they are hard on purpose; the page shows false approval with and without them.

## Ground truth

The file system first (the sentinel, the marker, the job's `DONE` and step files), then the transcript's tool result
(allowed or "doesn't want to proceed"), the prompts the session received after the clip started (a send), the
interruption marker (a stop), and the harness's own speech within 15 s after the clip (an answer). `check.py` has the
order. For the nothing class, a spoken reply is scored correct as well as no action: speech alone does not act on the
agent; the confusion matrix shows the raw classes.

## Arms

Every arm: `claude --model claude-haiku-5-5 --permission-mode default` in a pty, a fresh `CLAUDE_CONFIG_DIR` in the
item's /tmp folder, the API key in its environment only, HOME untouched, the same settings file (logging hooks, a read
deny on `bench/conversational/`). Pointe adds only `--plugin-dir`.

| Arm | What it is |
|---|---|
| `pointe` | A fresh daemon per item run (isolated state folder, a port in the run's range, its own uv environment, `POINTE_LINK_DIR` in /tmp), the session joined with `/pointe:voice`, Pointe's default setup, a call client on the page's WebSocket protocol. The utterance is played once Pointe has read the prompt out. |
| `llm-router` | Soniox real-time (Pointe's default ears and model) on the clip, one call to the brain model Pointe's default setup resolves to (effort low), the public prompt in `../adapters/llm_router_prompt.txt`; acts with keypresses and typing on the same pty; speaks answers through local Kokoro. The baseline for comparisons. |
| `naive` | Keyword rules, ours: Soniox, then yes-words approve, no-words deny, stop-words send Escape, anything else is typed in (not while a dialog is open). Speaks each agent turn's final message through Kokoro. Fails the adversarial set by construction; never in a headline comparison. |
| `keyboard` | The 30 clear yes and no items by keypress (Enter on the default "Yes", Escape): shows each fixture approves and denies. |
| `null` | Does nothing, on a seeded 20 items: its outcome is fixed by construction and each run still costs a session set-up, so it is confirmed on a sample. |

A repeat of 20 seeded items for `pointe` and `llm-router` gives the flip rate. All arms were written by the team whose
product is under test.

## Rules the runner enforces

- Preflight before the run: a `claude -p` probe with the identical environment reports `apiKeySource:
  ANTHROPIC_API_KEY`, the fresh config folder holds no login, and only Claude Code's built-in plugins load. Otherwise
  it stops.
- Every destructive command is asserted to resolve inside the item's /tmp folder before the run.
- A run where the agent never asks (or asks in another mode, or runs the command unasked) is `setup_failed`, rerun once,
  then excluded with the count shown per arm.
- The ledger (`../results/ledger.jsonl`) is read before every launch; a launch needs `workers x $0.12` of headroom under
  the cap.
- Ports 7860 and 7443 are refused; the owner's `~/.local/bin/pointe` is hashed before and after every run.
- Rows are scrubbed (no home path, no key-shaped text, no absolute path outside /tmp) before they are written.
- At the end every process with the run's folders in its command line, and anything listening on the run's ports, is
  killed.

## Limits

- Synthetic speech from four clean voices: an upper bound for every arm. Kokoro is also Pointe's local voice.
- One utterance per item and no follow-up: a harness that asks again ("Should it?") gets no second answer.
- The Pointe arm was run again after Pointe fixed what this benchmark found (Pointe 84eafbc; same items, seeds and
  settings; `run.py report <earlier run> <rerun>` keeps the reference arms' earlier rows). The earlier run had no
  interrupt for a Claude Code session. At 84eafbc a spoken stop ends the turn through Claude Code's hooks, the only
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
  them: 15 adversarial items it could not approve and 7 clear yes it could not grant. At 84eafbc both are said ("empty
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
