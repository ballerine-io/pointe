# Gate benchmark (`CLAUDE_VOICE_CHECKER`), 2026-11-06

The gate decides if a proposed send is what the user asked for now. Source: `tests/test_relevance_live.py`, 24 cases, two runs per model, daemon limits (5 s timeout, token limit as called). `RUN_LIVE=1 CLAUDE_VOICE_CHECKER=<vendor:model> uv run pytest -q tests/test_relevance_live.py`.

| Model | Failures, run 1 / run 2 (of 24) |
|---|---|
| gemini-3.5-flash-lite | 0 / 0 |
| gpt-5.6-luna | 1 / 2 |
| gpt-5-mini | 2 / 1 (slow) |
| gpt-6-luna | 2 / 2 |
| claude-haiku-5-5 | 3 / 2 |
| gpt-5.4-mini | 4 / 2 |
| gpt-6-sol | 4 / 4 |
| gpt-6.1-terra | 6 / 6 |
| claude-sonnet-5-5 | 7 / 5 |
| claude-opus-5-5 | 7 / 7 |
| gemini-4-argon | 14 / 15 |
| claude-fable-5-1 | 19 / 13 |
| gemini-3.8-flash | 22 / 18 |

Limits: these cases and the gate prompt were tuned against gemini-3.5-flash-lite, which favours it. Most gemini-3.8-flash failures came from the 5 s timeout or token limit. A gate must answer in well under a second or two, so a slow model is not usable here even when its judgement is good. The expected answers were written by one author.

An earlier run overstated failures: its cached SDK client was bound to a closed event loop. These numbers come from the fixed harness (`fresh_clients` in `tests/test_relevance_live.py`), with every model re-run.
