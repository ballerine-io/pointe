# Streaming text-to-speech benchmark (English and Hebrew)

Run 2026-11-05/06 with `.venv/bin/python -I bench/tts_bench.py run --reps 3` then `report`. Source: `bench/tts_bench.py`,
corpus `bench/tts_corpus.py`. Raw rows: `bench/results/tts-raw.jsonl`. Listen to `bench/results/tts-samples/`
(one clip per model per language: en04, he04, mx04; the invoice, money and date sentence).

## Method

- Corpus: 24 short assistant replies, 8 English, 8 Hebrew, 8 mixed Hebrew with English technical terms (invented product
  names Quillfox, Brindle API, Nimbus Ledger, Orbitkit; numbers, dates, money, "PR", "staging"). Each clip synthesised 3 times:
  72 runs per model, 24 clips x 3 reps, 0 failed runs.
- Latency: TTFB = request sent to first audio byte, on an already-open connection (HTTP keep-alive or open WebSocket, as in
  a live pipeline; connection setup is excluded). Total = request to last byte. RTF = total / audio duration (below 1 is
  faster than real time). Vendors ran in parallel with each other, sequentially within a vendor. From one laptop on one
  network path; a server near the vendor would show lower numbers.
- p50 / p95 pooled over all 72 runs, with 95% cluster-bootstrap CIs (2,000 resamples of clips, since the 3 reps of a clip are
  not independent). With 72 runs, p95 rests on ~4 slowest runs: treat it as indicative.
- Intelligibility: every synthesised clip is transcribed by Soniox `stt-rt-v6` (hints en, he) and scored against the source
  text: lowercase, punctuation and hyphens removed, thousands commas removed, `$4,250` and `4,250 dollars` equal, English number
  words to digits, ordinals stripped. Hebrew number words are NOT converted.
- Hebrew-as-Hebrew: a Hebrew clip passes if WER <= 0.5 and at least 80% of the returned letters are Hebrew script; a mixed
  clip passes if WER <= 0.5 and its Hebrew share is at least half the source's. Verdict: PASS if >= 80% of Hebrew clips pass,
  PARTIAL 30-80%, FAIL below.
- Voices: one fixed voice per vendor for all languages (ElevenLabs stock voice, Gemini Charon, Soniox Adrian). Voice choice
  affects results and was not varied.
- Cost: vendor list price, read 2026-11-05 (sources in the table). Gemini and Soniox bill tokens, so $/1k chars is derived
  from measured audio seconds (25 audio tokens per second) and 0.3 text tokens per character.

clips: 24, repetitions per clip: 3

## Latency and speed (all languages pooled)

| model | runs ok/tried | TTFB p50 [95% CI] | TTFB p95 [95% CI] | total p50 | RTF p50 | audio s/clip |
|---|---|---|---|---|---|---|
| elevenlabs/eleven_flash_v2_5 | 72/72 | 174 ms [173-177] | 182 ms [180-183] | 0.24 s | 0.05 | 4.9 |
| elevenlabs/eleven_turbo_v2_5 | 72/72 | 192 ms [188-194] | 220 ms [205-225] | 0.23 s | 0.05 | 5.0 |
| elevenlabs/eleven_v4_turbo | 72/72 | 213 ms [205-223] | 309 ms [235-327] | 0.70 s | 0.13 | 5.4 |
| elevenlabs/eleven_v4 | 72/72 | 711 ms [692-739] | 942 ms [851-979] | 1.68 s | 0.31 | 5.4 |
| elevenlabs/eleven_v3_conversational | 72/72 | 181 ms [176-188] | 205 ms [198-206] | 0.92 s | 0.17 | 5.4 |
| gemini/gemini-3.8-flash-tts | 72/72 | 733 ms [617-823] | 961 ms [898-1033] | 1.78 s | 0.37 | 4.8 |
| gemini/gemini-3.8-flash-lite-tts | 72/72 | 441 ms [429-458] | 534 ms [527-547] | 1.15 s | 0.24 | 4.8 |
| soniox/tts-rt-v2 | 72/72 | 301 ms [296-306] | 326 ms [318-670] | 4.05 s | 0.78 | 5.1 |
| openai/gpt-4o-mini-tts | 72/72 | 799 ms [762-898] | 1815 ms [1471-2133] | 1.83 s | 0.26 | 7.1 |

## TTFB p50 by language (ms)

| model | en | he | mix |
|---|---|---|---|
| elevenlabs/eleven_flash_v2_5 | 175 | 174 | 174 |
| elevenlabs/eleven_turbo_v2_5 | 189 | 194 | 193 |
| elevenlabs/eleven_v4_turbo | 211 | 204 | 223 |
| elevenlabs/eleven_v4 | 721 | 695 | 738 |
| elevenlabs/eleven_v3_conversational | 172 | 191 | 183 |
| gemini/gemini-3.8-flash-tts | 733 | 715 | 715 |
| gemini/gemini-3.8-flash-lite-tts | 441 | 444 | 434 |
| soniox/tts-rt-v2 | 304 | 300 | 297 |

## Round-trip intelligibility (Soniox stt-rt-v6 transcribes each clip)

Mean WER, 95% bootstrap CI over clips; Hebrew-as-Hebrew = share of clips that are intelligible (WER <= 0.5) and returned in Hebrew script.

| model | WER en | WER he | WER mix | CER mix | Hebrew-as-Hebrew he | Hebrew-as-Hebrew mix | Hebrew verdict | vendor claims Hebrew |
|---|---|---|---|---|---|---|---|---|
| elevenlabs/eleven_flash_v2_5 | 0.035 [0.008-0.066] (n=24) | 1.110 [0.960-1.369] (n=24) | 0.803 [0.749-0.857] (n=24) | 0.588 | 0% | 0% | FAIL | False |
| elevenlabs/eleven_turbo_v2_5 | 0.036 [0.008-0.071] (n=24) | 1.040 [0.975-1.112] (n=24) | 0.825 [0.780-0.869] (n=24) | 0.642 | 0% | 0% | FAIL | False |
| elevenlabs/eleven_v4_turbo | 0.000 [0.000-0.000] (n=24) | 0.022 [0.000-0.051] (n=24) | 0.266 [0.221-0.315] (n=24) | 0.198 | 100% | 100% | PASS | True |
| elevenlabs/eleven_v4 | 0.011 [0.000-0.028] (n=24) | 0.010 [0.000-0.019] (n=24) | 0.221 [0.179-0.265] (n=24) | 0.162 | 100% | 100% | PASS | True |
| elevenlabs/eleven_v3_conversational | 0.025 [0.000-0.050] (n=24) | 0.049 [0.014-0.090] (n=24) | 0.394 [0.337-0.455] (n=24) | 0.302 | 100% | 96% | PASS | True |
| gemini/gemini-3.8-flash-tts | 0.019 [0.000-0.044] (n=24) | 0.018 [0.004-0.033] (n=24) | 0.232 [0.180-0.287] (n=24) | 0.219 | 100% | 100% | PASS | True |
| gemini/gemini-3.8-flash-lite-tts | 0.028 [0.003-0.056] (n=24) | 0.020 [0.003-0.040] (n=24) | 0.261 [0.204-0.322] (n=24) | 0.215 | 100% | 96% | PASS | True |
| soniox/tts-rt-v2 | 0.025 [0.000-0.050] (n=24) | 0.019 [0.003-0.039] (n=24) | 0.270 [0.224-0.320] (n=24) | 0.171 | 100% | 100% | PASS | True |
| openai/gpt-4o-mini-tts | 0.025 [0.000-0.050] (n=24) | 0.032 [0.013-0.057] (n=24) | 0.254 [0.183-0.326] (n=24) | 0.180 | 100% | 96% | PASS | True |

## Cost per 1,000 characters (USD, list price read 2026-11-05)

| model | $/1k chars | basis |
|---|---|---|
| elevenlabs/eleven_flash_v2_5 | 0.0400 | elevenlabs.io/pricing/api, row 'Flash / Turbo' |
| elevenlabs/eleven_turbo_v2_5 | 0.0400 | elevenlabs.io/pricing/api, row 'Flash / Turbo' |
| elevenlabs/eleven_v4_turbo | 0.0400 | elevenlabs.io/pricing/api, row 'v4 Turbo' |
| elevenlabs/eleven_v4 | 0.0800 | elevenlabs.io/pricing/api, row 'v4' |
| elevenlabs/eleven_v3_conversational | 0.0400 | elevenlabs.io/pricing/api, row 'v3 Conversational' |
| gemini/gemini-3.8-flash-tts | 0.0177 | ai.google.dev/gemini-api/docs/pricing; intro price to 2026-12-31, doubles on 2027-01-01 |
| gemini/gemini-3.8-flash-lite-tts | 0.0119 | ai.google.dev/gemini-api/docs/pricing; intro price to 2026-12-31, doubles on 2027-01-01 |
| soniox/tts-rt-v2 | 0.0464 | soniox.com/pricing; audio tokens per second NOT published on the page: 25/s ASSUMED (same as Gemini) |
| openai/gpt-4o-mini-tts | 0.0349 | developers.openai.com/api/docs/pricing; audio tokens per second NOT published: 25/s ASSUMED |

Failed runs: 0

## Notes and limitations

Measured:
- Latency, speed, round-trip WER and the Hebrew check above, for every row.
- ElevenLabs `eleven_flash_v2_5` and `eleven_turbo_v2_5` do not speak Hebrew: their Hebrew output came back as Latin-letter
  gibberish (e.g. `HBNY SHLHPRVTHS2AMGB...`) and WER is about 1.0. Their model list (`/v1/models`) also omits `he`. They are English only.
- Gemini TTS streams: first chunk arrives well before the last (TTFB 0.44 s vs total 1.15 s for flash-lite).
- `eleven_v3_conversational` and `eleven_v4_turbo` stream with ~0.2 s TTFB and speak Hebrew. `eleven_v4` streams, with 0.7 s TTFB.
- Soniox TTS TTFB is 0.3 s, but total time is about 0.78 x audio duration (RTF 0.78), i.e. it delivers audio near real-time pace.

Assumed or not verified:
- Quality by ear (naturalness, accent, prosody, Hebrew pronunciation of English terms) is NOT measured. WER only shows
  intelligibility to one recogniser. Listen to the samples.
- The round-trip recogniser is Soniox. Soniox TTS may be favoured by its own recogniser, and mixed-language WER (0.21-0.83) is inflated for
  all vendors because the recogniser writes English terms in Hebrew letters (`build` -> `בילד`), which counts as a word error. Read
  mixed-clip rankings with the CER column and with caution: differences of ~0.05 WER between the top vendors are within noise.
  No second recogniser was used as a cross-check.
- OpenAI `gpt-4o-mini-tts`: its audio tokens per second are not published and 25/s is assumed, so its $/1k chars is an estimate.
- Soniox audio tokens per second are not published on its pricing page; 25/s (Gemini's rate) is assumed, so its $/1k chars is an estimate.
  Gemini's price is an introductory price that doubles on 2027-01-01.
- ElevenLabs prices are plan-independent API list prices; the page row "Flash / Turbo" is assumed to cover v2.5 Flash and Turbo.
  `eleven_v3` (non-conversational) was not benchmarked: it is not a low-latency model.
- Corpus is 24 clips of invented text: fine for ranking big gaps, not for small ones. Not tested: long replies, streamed
  text-in (sentence by sentence), concurrency, other voices, other networks, WebSocket variants of ElevenLabs.
- Spend: estimated under $3 total across vendors (about 21k ElevenLabs characters, a few cents of Gemini and Soniox, plus the STT runs). Not read from vendor billing.
