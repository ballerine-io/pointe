# Conversation quality suite

43 scripted multi-turn dialogues, spoken in synthetic voices, against real throwaway Claude Code sessions, scored
against [RUBRIC.md](RUBRIC.md): latency, turn-taking, accuracy, brevity and naturalness, recovery, orchestration across
sessions, safety, mixed English and Hebrew, and a weak network. The same dialogues run through Pointe and through a plain
router (Soniox ears, one Sonnet call per utterance, Pointe's own voice), so the score is the difference Pointe makes.

- `dialogues.toml`: the dialogues and what each turn expects. Invented projects (`dialogues/fixtures.py`), invented
  lines; each failure pattern seen on real calls is rebuilt in invented words.
- `voices.toml`: four native Kokoro voices, four accented ones (a Kokoro voice of another language reading English), and
  an Israeli voice for Hebrew, mixed speech and accented English (OpenAI gpt-4o-mini-tts).
- `dialogues/play.py`: one dialogue on one arm, the scripted user (no model plays the user), and the record.
- `dialogues/score.py`: every measure from the record; `dialogues/judge.py`: a blind Fable naturalness score.
- `adapters/`: Pointe on an isolated daemon (own state under /tmp, ports 9800-9899) and the plain router.

```
uv sync --locked --extra local
uv run --locked --extra local python bench/conversational/dialogues/run.py corpus
uv run --locked --extra local python bench/conversational/dialogues/run.py run --arm pointe,llm-router --budget-usd 150
uv run --locked --extra local python bench/conversational/dialogues/run.py score <run-id> [<run-id> ...] [--turns]
uv run --locked --extra local python bench/conversational/dialogues/run.py judge <run-id> --arm pointe,llm-router
uv run --locked --extra local python bench/conversational/dialogues/run.py report baseline=<ids> before=<ids> after=<ids>
```

The Pointe arm runs a pristine export of a committed Pointe (`--commit`, default HEAD) under /tmp. Keys come from the
Keychain or the environment, into the one process that needs them. `results/ledger.jsonl` keeps the spend of every run,
computed from usage and list prices, and the runner refuses a launch past `--budget-usd`.

Limits: synthetic speech only; one machine, shared with other work (the load average is in every row); the scripted
user waits for quiet before speaking and does not adapt; small samples, so close numbers do not rank.
