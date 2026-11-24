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
| openai/gpt-4o-mini-tts | 1044 | 757 | 777 |

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
