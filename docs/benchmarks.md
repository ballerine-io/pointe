# Speech component benchmarks

These benchmarks chose Pointe's default vendors: one role at a time (ears, brain, mouth, gate, voice lock), on
**synthetic speech and invented cases**. Most were run once, between 2026-11-05 and 2026-11-25, on builds before 0.8.5,
and they have not been re-run on 0.8.5. Each line gives its date, its method and where its raw rows are. The scripts
are in `bench/`; re-run them with your own keys.

What the whole product does on a call (first word, accuracy, approvals, turn-taking, recorded people) is measured
separately, on a tagged release: [docs/benchmarks/README.md](benchmarks/README.md), and on the
[site](https://eng.ballerine.com/pointe/benchmarks/).

Raw rows behind this page: `bench/results/raw/` (synthetic, no corpus audio).

## Ears (speech to text), 2026-11-11/12

`bench/stt_extra.py`; report `bench/results/report.txt`; raw `bench/results/raw/stt-results.jsonl` and
`stt-judged.json`. 70 utterances (English, Hebrew, mixed, short yes/no) x 4 synthetic ElevenLabs voices x clean and
12 dB noise = 560 clips, streamed at real-time pace, one run per clip.

| ears | intent correct (model judge) | word error (computed) |
|---|---|---|
| Soniox stt-rt-v5 | 95.4% | 0.062 |
| **Soniox stt-rt-v6** (default) | **95.9%** | **0.063** |
| gemini-3.5-transcribe-live | 92.0% | 0.094 |
| OpenAI gpt-4o-transcribe | 90.9% | 0.209 |
| OpenAI gpt-4o-mini-transcribe | 85.5% | 0.203 |
| Gemini Live, as a whole | 79.6% | 0.240 |
| OpenAI gpt-live-transcribe | 81.1% | 0.195 |
| ElevenLabs scribe_v2_realtime | 68.9% | 0.378 |
| Whisper large-v3-turbo, local (MLX, M5 Pro, 2026-11-13) | 85.7% | 0.219 |

- **Intent is judged by a model**, `gemini-3.5-flash` at temperature 0, blind to the vendor. It is from the same vendor
  as two rows it grades. Its verdicts are noisy: of 417 groups of identical reference and transcript pairs, 37 got
  verdicts that disagree with their group's majority, and it passed a Hebrew request transcribed into Arabic script.
  A difference of a few points between rows is not a ranking. Word error is computed, not judged; it is a mean of
  per-clip rates, so a one-word clip weighs as much as a sentence.
- **No latency column.** The earlier table gave latency per vendor, but the vendors were not timed the same way:
  Soniox at its first end token (some clips came out negative), ElevenLabs at its last commit after a 0.5 s pause,
  OpenAI after a 500 ms server pause, Gemini with a fixed 0.4 s added, and clips that never gave a final were dropped
  from the percentiles. Those numbers do not compare, so they are not published. The time Pointe takes end to end is
  measured on the release benchmarks instead.
- Pointe uses `stt-rt-v6` because Soniox removes v5 on 2026-12-15, not because v6 measured better.

## Brain, 2026-11-25

`bench/first_word_bench.py brains` with `bench/brain_bench.py`'s 84 cases, prompts, stub tools and rubric, through the
real `brain.Brain`; raw `bench/results/raw/first_word.jsonl`; `.venv/bin/python bench/first_word_bench.py report`
recomputes it. "Right" is the rubric's code checks, not a model judge. Load median 9.5.

| brain | replies (84 cases x repeats) | right | first sentence median / p90 | $ a reply |
|---|---|---|---|---|
| **anthropic:claude-sonnet-5-5** (default) | 336 | 81.5% | 2.21 / 3.82 s | 0.0048 |
| openai:gpt-6-sol | 252 | 83.3% | 1.85 / 3.47 s | 0.0194 |
| anthropic:claude-haiku-5-5 (fallback) | 84 | 78.6% | 2.23 / 3.38 s | 0.0004 |
| openai:gpt-6-luna | 84 | 75.0% | 2.42 / 3.90 s | 0.0012 |
| gemini:gemini-3.5-flash-lite | 84 | 72.6% | 1.27 / 2.23 s | 0.0033 |
| gemini:gemini-3.8-flash | 61 of 84 answered | 88.5% | 4.69 / 9.30 s | 0.0066 |

On the same cases, Sonnet was right where gpt-6-sol was wrong 23 times, and the reverse 28 times, of 252: no
difference. The prompts were written and tuned on Sonnet, which favours it. Synthetic cases; stub tools answer at once,
so these times are shorter than on a call. The earlier figures on this page (78 cases, Sonnet 91.9%) had no report or
raw rows behind them and were removed.

## Mouth (text to speech), 2026-11-05/06

`bench/tts_bench.py run --reps 3`; report `bench/results/tts.md`; raw `bench/results/raw/tts-raw.jsonl`. 24 replies
(8 English, 8 Hebrew, 8 mixed) x 3, one laptop, one network path, connection already open.

| mouth | first audio p50 / p95 | word error EN / HE | Speaks Hebrew | $ per 1k chars |
|---|---|---|---|---|
| **eleven_v4_turbo** | 213 / 309 ms | 0.00 / 0.02 | yes | 0.04 |
| eleven_v3_conversational | 181 / 205 ms | 0.03 / 0.05 | yes | 0.04 |
| eleven_flash_v2_5 | 174 / 182 ms | 0.04 / 1.11 | **no** | 0.04 |
| soniox tts-rt-v2 | 301 / 326 ms | 0.03 / 0.02 | yes | about 0.05 |
| gemini-3.8-flash-lite-tts | 441 / 534 ms | 0.03 / 0.02 | yes | 0.012 |
| gemini-3.8-flash-tts | 733 / 961 ms | 0.02 / 0.02 | yes | 0.018 |
| OpenAI gpt-4o-mini-tts | 799 / 1815 ms | 0.03 / 0.03 | yes | about 0.035 |

Word error is a round trip through a Soniox recognizer (Soniox is also a row here). The report names `stt-rt-v6`, but
the run predates v6 and the rows do not record which model heard them. How a voice sounds to a person is not measured.

## The rest, each once, synthetic

- **Gate** (2026-11-06): `tests/test_relevance_live.py`, 24 cases, two runs per model; `gemini-3.5-flash-lite` failed
  none. The cases were written while the gate was tuned on that model. [`bench/results/gate.md`](../bench/results/gate.md)
- **Voice lock**: 19 synthetic voices (other macOS voices as impostors). At the thresholds the daemon uses, a stranger's
  sentence passes 1.6% of the time (16 of 1,026) and yours fails 3.5% (2 of 57); a short word after a match passes for a
  stranger 1.3% (9 of 684) and fails for you 5.3% (2 of 38). [`bench/results/speaker.md`](../bench/results/speaker.md)
- **Vocabulary** (Soniox v5): a made-up name spelled right 25 of 64 times without hints, 60 of 64 with them.
  [`bench/results/vocab.md`](../bench/results/vocab.md)
- **Challenge me** (2026-11-12): 15/30 to 30/30 on Sonnet, 21/30 to 30/30 on Gemini Flash, on the same six cases the
  brackets were designed on; no held-out cases. [`bench/results/challenge.md`](../bench/results/challenge.md)
- **Whisper** (Soniox v5, made by lowering synthetic voices; no person whispered): word error 1.4% at -18 dB, 18.4% at
  -30 dB. [`bench/results/whisper.md`](../bench/results/whisper.md)
- **Fully local** (`pointe local`, M5 Pro, 2026-11-13, load 17 to 154): brain `gemma-4-26b-a4b-it` passed 76.9% of the
  78 cases of that day, median reply 3.4 s with stub tools; a plain question end to end took 11.6 s.
  [`bench/results/local.md`](../bench/results/local.md)
- **Voice stays on your Mac** (`pointe local voice`, 2026-11-13): Kokoro on MLX starts English speech in 185 ms at the
  median; 30 of 35 audio checks passed. [docs/features/voice-stays-local.md](features/voice-stays-local.md#measured)
- **Whole setups** (2026-11-13, Soniox v5, one run each): [`bench/results/combinations.md`](../bench/results/combinations.md).
  Its counts treat a skipped check as passed.

Not measured for any component here: a recorded person.

## Cost arithmetic

A busy hour on the best setup: brain 60 replies at $0.0045, about $0.27. Mouth 60 replies of 30 words, about 11,000 characters at $0.04 per
1,000, about $0.43. Reader 10 reports at $0.01, about $0.10. Soniox $0.12 per stream hour with up to two streams, about $0.24. About $1 in all.
Prices read 2026-11-06; check them. This is arithmetic, not a metered bill.

Other setups, the same hour, from the measured cost per reply in `bench/results/brain_substance.md` and the mouth table above:

| Keys | Brain (60) | Reader (10) | Mouth (11,000 chars) | Ears (the call open for the hour) | About |
|---|---|---|---|---|---|
| Anthropic, Soniox | $0.27 | $0.10 | $0.55 (Soniox) | $0.24 | $1.20 |
| Gemini only, billing on | $0.25 | $0.03 | $0.13 | $0.30 to $0.54 | $0.70 to $0.95 |
| Gemini only, free tier | $0 | $0 | $0 | $0 | $0 until the quota ends |
| OpenAI only | $0.16 to $1.16 | $0.04 | $0.39 | $0.36 | $0.95 to $1.95 |
| Anthropic, Gemini, voice on the Mac | $0.27 | $0.10 | $0 (Kokoro, local) | $0 (Whisper, local) | $0.40 |
| Gemini only, voice on the Mac (not run through the audio suite) | $0.25 | $0.03 | $0 | $0 | $0.30 |
| Fully local | $0 | $0 | $0 | $0 | $0 |

The gate adds a small amount on every setup. Two runs disagree on what `gpt-6-sol` costs a reply: $0.0027
(`bench/results/brain_substance.md`) and $0.0194 (the 2026-11-25 brain run above); the two scripts count cache writes and
thinking tokens differently, so the OpenAI row shows both.

Where the ears prices come from, read on the vendors' pages on 2026-11-19: Soniox real-time transcription $0.12 an hour
per stream ([soniox.com/pricing](https://soniox.com/pricing)); `gemini-3.5-transcribe-live` $0.005 a minute of audio in
and $0.004 a minute of text out, so $0.30 to $0.54 an hour ([Google's pricing page](https://aistudio.google.com/docs/pricing));
`gpt-4o-transcribe` about $0.006 a minute ([OpenAI's pricing page](https://developers.openai.com/api/docs/pricing)). The
brain and reader prices behind the per-reply costs (read 2026-11-06) were the same on those pages on 2026-11-19: Claude
Sonnet 5.5 $2 and $10 per million tokens in and out ([Anthropic](https://platform.claude.com/docs/en/about-claude/pricing)),
`gemini-3.8-flash` $0.75 and $3.75, `gpt-6-sol` $2 and $10. Google's page says `gemini-3.8-flash` and
`gemini-3.8-flash-lite-tts` double on 2027-01-01: the two paid Gemini-only rows then rise by about $0.40 and $0.30. The
free tier and its limits: [docs/install.md](install.md#try-it-for-free-or-cheap).
