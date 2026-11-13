# Benchmarks

The default models come from these runs. Scripts and reports are in `bench/`; re-run them with your own keys. All data
is synthetic.

- **Brain and reader:** `bench/brain_bench.py`, report in `bench/results/brain.md`. Real tool and speech path; 78 brain
  cases and 17 reader cases. On 78 cases with the daemon's own context block (2026-11-12), `claude-sonnet-5-5` passes
  91.9% ignoring length (95% CI 85.9% to 97.0%), median reply 1.8 s; its fallback `claude-haiku-5-5` passes 88.0%; `gemini-3.8-flash` passes 94.9%
  (89.7% to 98.7%), median reply 2.7 s, with no unwanted sends against Sonnet's 9. The intervals overlap. Sonnet's 9 are all attempts to relay an
  approval that must be typed in the terminal; the daemon now refuses those in code, and the bench still counts the attempt.
  The earlier ranking on 66 cases, in `bench/results/brain_substance.md`, had Sonnet at 95.5%; nothing tested there beat
  it measurably, including Opus, Fable, high effort and 11 OpenAI models. Those prompts were tuned on Sonnet, which
  favours it. From that earlier run, not re-measured: `gemini-4-argon` 93.5% but 17 s.
- **Gate:** `tests/test_relevance_live.py`, report in `bench/results/gate.md`.
- **Fully local (`pointe local`):** the same benchmarks on an M5 Pro with 64 GB, 2026-11-13, report in
  `bench/results/local.md`. Brain `gemma-4-26b-a4b-it` (MLX 4-bit) passes 76.9% (67.9% to 85.5%) ignoring length,
  median reply 3.4 s, against 91.9% and 1.8 s for `claude-sonnet-5-5`; as the reader it passes 51.0%
  against 100% for Sonnet on 51 reports. Measured with other work running on the Mac.
- **Voice stays on your Mac (`pointe local voice`):** local Whisper and Kokoro on MLX with the cloud brain, 2026-11-13,
  in [docs/features/voice-stays-local.md](features/voice-stays-local.md#measured). Kokoro on MLX, as the daemon runs it,
  starts English speech in 185 ms at the median (kokoro-onnx 750 ms in the same run); the whole setup passed 30 of 35
  audio checks.
- **Which vendors and whole setups are covered, and what is not:** `bench/results/combinations.md`.
- **Ears:** `bench/stt_extra.py`, report in `bench/results/report.txt`. 70 utterances (English, Hebrew, mixed, short
  yes/no) x 4 voices x clean/noisy = 560 clips, at real-time pace, with a blind intent judge.
- **Mouth:** `bench/tts_bench.py`, report in `bench/results/tts.md`. Time to first audio, plus intelligibility by round trip
  through a recognizer. Not covered: how it sounds to a person (samples are generated locally to listen to).

| ears | intent correct | word error | latency p50 / p90 |
|---|---|---|---|
| **Soniox stt-rt-v5** | **95.4%** | **0.062** | **0.36 / 1.29 s** |
| Soniox stt-rt-v6 | 95.9% | 0.063 | 0.38 / 2.18 s |
| gemini-3.5-transcribe-live | 92.0% | 0.094 | 0.72 / 1.62 s |
| OpenAI gpt-4o-transcribe | 90.9% | 0.209 | 1.16 / 1.96 s |
| OpenAI gpt-4o-mini-transcribe | 85.5% | 0.203 | 1.09 / 1.97 s |
| Gemini Live, as a whole | 79.6% | 0.240 | 1.13 / 2.45 s |
| OpenAI gpt-live-transcribe | 81.1% | 0.195 | 0.66 / 1.59 s |
| ElevenLabs scribe_v2_realtime | 68.9% | 0.378 | 0.77 / 1.78 s |
| Whisper large-v3-turbo, local (MLX, M5 Pro) | 85.7% | 0.219 | 0.76 / 1.25 s |

The local row is from a run on 2026-11-13 on the same 560 clips and the same judge; its latency is the voice detector's
0.2 s wait plus the time to transcribe the clip on the Mac, not a network path, so it compares with the others only roughly.
Details: [docs/features/local.md](features/local.md#measured).

The v5 and v6 accuracy gap is inside the confidence intervals. v5 stays the default because v6 never finalised 3 clips of 560 and waited over 1 s more often (17.6% of clips against 13.9%).

| mouth | first audio p50 / p95 | word error EN / HE | Speaks Hebrew | $ per 1k chars |
|---|---|---|---|---|
| **eleven_v4_turbo** | 213 / 309 ms | 0.00 / 0.02 | yes | 0.04 |
| eleven_v3_conversational | 181 / 205 ms | 0.03 / 0.05 | yes | 0.04 |
| eleven_flash_v2_5 | 174 / 182 ms | 0.04 / 1.11 | **no** | 0.04 |
| soniox tts-rt-v2 | 301 / 326 ms | 0.03 / 0.02 | yes | about 0.05 |
| gemini-3.8-flash-lite-tts | 441 / 534 ms | 0.03 / 0.02 | yes | 0.012 |
| gemini-3.8-flash-tts | 733 / 961 ms | 0.02 / 0.02 | yes | 0.018 |
| OpenAI gpt-4o-mini-tts | 799 / 1815 ms | 0.03 / 0.03 | yes | about 0.035 |

Limits: voices are synthetic, latency is from one laptop and one network, the round trip uses one recognizer, and the benchmark author is a model from a vendor under test. Each report lists its own limits.

## Cost arithmetic

A busy hour on the best setup: brain 60 replies at $0.0045, about $0.27. Mouth 60 replies of 30 words, about 11,000 characters at $0.04 per
1,000, about $0.43. Reader 10 reports at $0.01, about $0.10. Soniox $0.12 per stream hour with up to two streams, about $0.24. About $1 in all.
Prices read 2026-11-06; check them. This is arithmetic, not a metered bill.

Other setups, the same hour, from the measured cost per reply in `bench/results/brain_substance.md` and the mouth table above:

| Keys | Brain (60) | Reader (10) | Mouth (11,000 chars) | Ears | About |
|---|---|---|---|---|---|
| Anthropic, Soniox | $0.27 | $0.10 | $0.55 (Soniox) | $0.24 | $1.20 |
| Gemini only | $0.25 | $0.03 | $0.13 | not priced here | $0.40 plus ears |
| OpenAI only | $0.16 | $0.04 | $0.39 | not priced here | $0.60 plus ears |
| Anthropic, Gemini, voice on the Mac | $0.27 | $0.10 | $0 (Kokoro, local) | $0 (Whisper, local) | $0.40 |

The gate adds a small amount on every setup.
