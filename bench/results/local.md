# Fully local: the benchmarks, 2026-11-13

One Mac: Apple M5 Pro, 64 GB, macOS 27.0. Every number below comes from the repository's own benchmarks run on it, with
the scripts and commands named in each section. All data is synthetic, as in the other reports.

**Load.** Other work ran on this Mac during every run (a virtual machine, other test tracks, indexing): the load average
was between 17 and 154 while these were measured. Latency here is therefore an upper bound for a quiet Mac, and it is not
equally loaded across rows. Accuracy does not depend on load.

## Brain: 78 cases x 3

`bench/brain_bench.py run --role brain --repeats 3`, with the daemon's prompts frozen on 2026-11-13, each model alone on
`mlx_lm.server` 0.32.2 with thinking off (`--chat-template-args '{"enable_thinking": false}'`). Scored offline by the
same rubric (`bench/brain_bench.py substance`); not judged, so there is no judge column. Memory is the server's footprint
as macOS counts it (`footprint`), after the run.

| Model (MLX 4-bit) | Pass ignoring length (95% CI) | Failures of substance | Unwanted sends | Pass with length | Reply p50 / p95 s | Steps over 8 s | Memory |
|---|---|---|---|---|---|---|---|
| **gemma-4-26b-a4b-it** | **76.9% (67.9% to 85.5%)** | 69 of 234 | 16 | 70.9% | **3.4 / 9.2** | 1.1% | **17 GB** |
| Qwen3.6-35B-A3B | 74.8% (66.7% to 82.5%) | 76 of 234 | 18 | 70.9% | 3.6 / 13.3 | 5.1% | 20 GB |
| Qwen3.5-9B | 62.0% (52.6% to 71.4%) | 138 of 234 | 35 | 52.6% | 3.9 / 11.4 | 0.8% | 5.3 to 7.6 GB |
| Qwen3.8-27B (dense) | stopped after 12 replies | | | | 13.0 / 54.3 (max) | | 19 GB |

The published cloud numbers on the same 78 cases (`docs/benchmarks.md`, 2026-11-12): `claude-sonnet-5-5` 91.9%
(85.9% to 97.0%), median reply 1.8 s, 9 unwanted sends, all typed-approval relays the daemon refuses in code;
`gemini-3.8-flash` 94.9%, 2.7 s, none. The best local brain's interval does not reach either.

Gemma's 16 unwanted sends, by case: a typed approval relayed (5; the daemon refuses these in code), a cut-off or unclear
request sent instead of asked about (9: `cut_mid_word`, `unclear_rollback`, `unclear_he`), and a challenge-mode send
(2). It never asked a clarifying question on the 12 unclear cases. Hebrew cases passed 81% (29 of 36), English 76%.

Qwen3.8-27B was cut short: a reply took 13 s at the median, too slow to talk to whatever its accuracy. An earlier
one-repeat run through Ollama (`brain_substance.md`, `qwen3.8 (local)`) had it at 87.9% with a 26.7 s median.

## Reader: 17 cases x 3

`bench/brain_bench.py run --role reader`, gemma-4-26b-a4b-it as above.

| Model | Pass ignoring length (95% CI) | Failures of substance | Reply p50 / p95 s | Over the daemon's 10 s limit |
|---|---|---|---|---|
| gemma-4-26b-a4b-it (local) | 51.0% (31.4% to 68.6%) | 26 of 51 | 7.5 / 10.5 | 4 of 51 |
| claude-sonnet-5-5 (`brain_substance.md`) | 100.0% | 0 of 51 | 3.8 / 5.2 | 0 |

Many failures are of form, not content: 12 of the 25 failing reports had no `say` field, which the daemon needs to speak a report.
A report over 10 s goes out as an excerpt instead.

## Ears: 560 clips

`bench/stt_extra.py run --systems local-whisper-turbo,local-ivrit-turbo,local-whisper-large-v3 --concurrency 1`, then the
same scorer and judge (`gemini-3.5-flash`) as `report.txt`. Local Whisper does not stream: it transcribes a segment once
the voice detector closes it, so latency here is pipecat's 0.2 s detector wait plus the time to transcribe the clip.
Transcription alone took 0.56 s at the median and 1.05 s at p90 for large-v3-turbo.

| ears | intent correct (95% CI) | word error | latency p50 / p90 | English | Hebrew | Mixed | Short yes/no |
|---|---|---|---|---|---|---|---|
| **Whisper large-v3-turbo (MLX)** | **85.7% (82.9 to 88.4)** | 0.219 | 0.76 / 1.25 s | 87.5% | 93.3% | 75.0% | 90.0% |
| Whisper large-v3 (MLX) | 85.4% (82.3 to 88.0) | 0.221 | 1.09 / 1.58 s | 90.0% | 90.8% | 75.6% | 86.7% |
| ivrit-ai Whisper large-v3-turbo (MLX) | 76.8% (73.0 to 80.2) | 0.331 | 0.85 / 1.36 s | 37.5% | 95.0% | 87.5% | 96.7% |
| Soniox stt-rt-v5, for reference (`report.txt`) | 95.4% | 0.062 | 0.36 / 1.29 s | | | | |

Paired on the same clips (exact McNemar): turbo against large-v3, 480 against 478 correct, p = 0.89; turbo against
OpenAI gpt-4o-transcribe, p = 0.28; turbo against Soniox v5, p = 5e-9. The ivrit-ai model is the best on Hebrew and
mixed speech and writes English in Hebrew letters.

The cloud rows the local ones were paired with in this run come from the 2026-11-06/07 rows in `results.jsonl`, not the
2026-11-11/12 rerun that `report.txt` shows; the reference row above is the published one.

Whisper chose a third language for 24 of 120 short clips (Spanish, French, Italian, Polish, Arabic, Korean, Indonesian).

## Mouth: 24 clips x 3

`bench/local_tts_bench.py`: the corpus of `tts_bench.py` (8 English, 8 Hebrew, 8 mixed), whole replies, one model at a
time after a warm-up clip. Intelligibility is a round trip through local Whisper large-v3-turbo, not Soniox, so it does
not compare with `tts.md`.

| mouth | first audio, English p50 / p95 | first audio, all p50 / p95 | real-time factor p50 | word error EN / HE / mixed | Hebrew heard as Hebrew |
|---|---|---|---|---|---|
| Kokoro v1.0, kokoro-onnx (what the daemon runs) | 1283 / 4454 ms | 2979 / 5000 ms | 0.21 | 0.01 / 8.43 / 4.73 | 0 of 24 |
| Kokoro 82M, mlx-audio 0.6.5 | 229 / 277 ms | 639 / 1216 ms | 0.04 | 0.00 / 8.55 / 4.71 | 0 of 24 |
| Chatterbox Multilingual v3, mlx-audio 0.6.5 | 2407 / 3046 ms | 2741 / 3734 ms | 0.56 | 0.04 / 0.87 / 1.06 | 0 of 24 |
| eleven_v4_turbo, for reference (`tts.md`) | 213 ms (all languages) | | | | |

kokoro-onnx yields a whole utterance at once, so its first audio is the time to make all of it. The daemon sends one
sentence at a time, so in a call it waits for one sentence, not a reply. Kokoro has no Hebrew voice: Hebrew text comes
out as noise. Chatterbox Multilingual claims Hebrew; its Hebrew was not intelligible to Whisper here.

## Install

`pointe local` downloaded nothing new in the final run (the models were cached from these runs): 0.4 GB of mlx-lm
environment, installed in 11 s, and the text model loaded and answered in 21 s. On a fresh cache it fetches Whisper
large-v3-turbo 1.6 GB, gemma-4-26b-a4b-it 15.4 GB and Kokoro 0.34 GB; a 1.5 GB model took 37 s from Hugging Face on this
link (about 40 MB/s), so the whole set is about 7 to 8 minutes at that rate.

## End to end

`tests/e2e/scenarios.py brain` (19 single-session checks: a real Claude Code session on `haiku`, synthetic user speech
over the call socket), with only `pointe local`'s config in an isolated state dir, on isolated ports, while a paid
Gemini key sat in the environment for the suite's transcriber: the daemon read no key. Load average 17 to 40.

**10 of 19 passed.** Passed: greeting, delegation, permission read-out and voice approval, the result summary, a delete
not done without the user, silence approving nothing, a yes approving, a no denying, a Hebrew request delegated as a
clear instruction, and a reconnect replaying nothing. Failed: the plain question (11.6 s, limit 3.5 s), barge-in (a brain
step over 8 s), a side question (5.8 s, limit 4 s), chat while research runs (6.3 to 7.2 s), the research report not
picked up, the follow-up from it (5.8 s), the Hebrew answer (not spoken in Hebrew), the fix asked in Hebrew (not landed
when checked), and knowing the session after a reconnect (a brain step over 8 s). The daemon log shows five brain steps
over 8 s. The multi-session and echo suites were not run.

The same suite, cloud setups, from `combinations.md`: 18 of 19 (default keys), 14 of 19 (Gemini only).

The first run found a bug: on Apple silicon, `ears: local` crashed at the first call, because pipecat's Whisper module
imports faster-whisper, which the local extra installs only on other machines. Fixed in `vendors._mlx_ears`, with a test.

## Limits

- One Mac, one day, a loaded machine. Latency on a quiet Mac, or on an M1 or M2 with less memory bandwidth, is not
  measured.
- The rubric and cases were tuned on cloud models; local models may be penalised for style the rubric does not forgive.
- No judge scores (the judge is a cloud model and was not run for these).
- Three repeats per case; the confidence intervals treat cases, not replies, as the unit.
