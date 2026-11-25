# The first word: brains, an opener model, and mouths (2026-11-25)

Run with `bench/first_word_bench.py` (new) and `bench/tts_bench.py`. Synthetic cases and sentences, one workstation,
load median 9. No default was changed by this work.

## Brains: the first checked sentence, and how often the reply is right

The 84 cases, prompts, stub tools and rubric of `bench/brain_bench.py`, through the real `brain.Brain` with the first
sentence said ahead as on a call. Seconds from the request; median and p90. "First sentence" is the first sentence that
passed the speech checks and was handed to the mouth, over all cases; "spoken replies" is the same over the cases
answered without a tool. Only Anthropic is read as it writes, so the others give their first sentence when the whole
reply is in.

| Brain | Replies | Right | First token | First sentence | Spoken replies | First tool call | $ a reply |
|---|---|---|---|---|---|---|---|
| anthropic:claude-sonnet-5-5 (default) | 252 | 81.3% | 0.89 / 1.24 | 2.25 / 3.75 | 1.33 / 3.22 | 1.95 / 3.17 | 0.0048 |
| openai:gpt-6-sol | 252 | 83.3% | - | 1.85 / 3.47 | 1.40 / 2.33 | 1.35 / 2.17 | 0.0194 |
| anthropic:claude-haiku-5-5 | 84 | 78.6% | 0.52 / 0.69 | 2.23 / 3.38 | 1.80 / 2.85 | 1.84 / 2.67 | 0.0004 |
| openai:gpt-6-luna | 84 | 75.0% | - | 2.42 / 3.90 | 1.39 / 2.57 | 1.25 / 2.01 | 0.0012 |
| gemini:gemini-3.5-flash-lite | 84 | 72.6% | - | 1.27 / 2.23 | 0.77 / 1.60 | 0.77 / 1.42 | 0.0033 |
| gemini:gemini-3.8-flash | 61 of 84 | 88.5% | - | 4.69 / 9.30 | 4.52 / 6.36 | 4.62 / 7.74 | 0.0066 |

Same cases, right with the default and wrong with the candidate / the reverse: gpt-6-sol 23 / 28 of 252; haiku 8 / 6
of 84; gpt-6-luna 15 / 10; flash-lite 12 / 5; gemini-3.8-flash 5 / 10 of 61.

- **No brain is both faster to the first word and right as often.** gpt-6-sol is right as often as the default (the
  23 / 28 split is not a difference) and it acts sooner: a send leaves 0.6 s earlier and its slow replies are shorter
  (p90 2.33 s against 3.22 s). On a spoken answer its median is 0.07 s behind, because Pointe cannot say its first
  sentence before the reply is whole. It costs four times as much a reply.
- **Haiku's first token is fast (0.52 s) and its first sentence is not.** It writes the speak call first less often,
  and more of its sentences are sent back by the checks.
- **Flash-Lite is the only brain under a second on spoken answers (0.77 s), and it is right 8.7 points less often.**
- gemini-3.8-flash failed 23 of 84 calls and took 4.5 s on the day: not a measure of the model, a measure of that day.
- One repeat for four of the six: differences of a few points between them are not evidence.

## An opener from a fast model in front of the brain

The model sees the user's words and the session names, and is asked for two to five words that stay true whatever the
answer turns out to be. Scored in code. "Claims": a result, a number, a yes or no, or more than six words. "Promises":
says an action is under way, on a case where the default brain then called no tool.

| Opener model | Cases | Said one | First token (med / p90) | Whole opener | Claims | Promises not kept |
|---|---|---|---|---|---|---|
| gemini:gemini-3.5-flash-lite | 84 | 73 | 0.46 / 0.58 | 0.46 / 0.58 | 3 | 14 |
| anthropic:claude-haiku-5-5 | 84 | 53 | 0.52 / 0.68 | 0.61 / 0.93 | 11 | 18 |
| openai:gpt-6-luna | 84 | 64 | 0.57 / 0.96 | 0.71 / 1.06 | 2 | 0 |

**Not safe.** Each model broke the rule: "Sure thing," to a delete that was then refused, "Let me check." before a
reply that checked nothing, a whole answer in place of an opener, and Haiku's own second thoughts read into the
speak text. An opener is said before the brain has decided, so it cannot be checked against what the brain will do.
An opener that is safe by construction is a fixed phrase, and a fixed phrase needs no model.

## Mouths: first audio byte

`bench/tts_bench.py`, 24 sentences (English, Hebrew, mixed), two repeats, on an open connection.

| Mouth | First byte p50 | p95 | English word errors | Hebrew |
|---|---|---|---|---|
| elevenlabs:eleven_v4_turbo (default) | 211 ms | 336 ms | 0.000 | pass |
| elevenlabs:eleven_flash_v2_5 | 169 ms | 177 ms | 0.077 | fail (word error rate 1.10) |
| soniox:tts-rt-v2 | 322 ms | 356 ms | 0.025 | pass |
| gemini:gemini-3.8-flash-lite-tts | 387 ms | 423 ms | 0.025 | pass |
| openai:gpt-4o-mini-tts | 609 ms | 1311 ms | 0.034 | pass |

**Keep the default.** Flash is 42 ms sooner at the median and steadier in the tail, and it cannot speak Hebrew. For a
user who never speaks Hebrew it is a small gain: `CLAUDE_VOICE_MOUTH=elevenlabs:eleven_flash_v2_5`.

## The floor with the best of each

From the end of the user's sound, on a turn a model answers (`tests/e2e/latency.py`, stage medians):

| Stage | Today | Best measured that is right as often |
|---|---|---|
| Final transcript | 0.45 s | 0.45 s (Soniox; no setting moved it) |
| First checked sentence | 0.9 to 1.3 s (first token 0.6 to 0.95, sentence 0.3) | the same: no brain beat it |
| Mouth, first byte | 0.21 to 0.25 s | 0.17 s, English only |
| Playback | 0.08 s | 0.08 s |
| **First sound** | **1.65 to 2.05 s** | **1.6 to 2.0 s** |

Nothing measured here brings a model-answered turn to 1.0 s with the speech check kept and the replies right as often.
What would: a brain whose first checked sentence is ready in 0.3 s (Flash-Lite's 0.77 s would give about 1.5 s, at 8.7
points fewer right replies), or reading OpenAI's and Gemini's replies as they are written, which this bench does not
measure and which is code in `vendors.py`, not a setup.
