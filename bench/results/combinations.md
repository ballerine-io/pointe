# Which vendors are covered, 2026-11-08

Each role is benchmarked on its own; a whole setup is then checked by the real audio suite (`tests/e2e/run_all.sh`), with each role set by `CLAUDE_VOICE_*`.

## Whole setups, real audio

2026-11-08, the current code (WebSocket call, 19 single-session checks, 12 multi-session, 4 echo). One run each; only the listed keys
were visible to the daemon (a Keychain shim refused the others). Counts are passes of 35.

| Keys | Ears / brain / reader / gate / mouth | Single | Multi | Echo | Total | Failures, from the daemon log |
|---|---|---|---|---|---|---|
| Soniox, Anthropic, Gemini, ElevenLabs (default) | stt-rt-v5 / sonnet / sonnet / flash-lite / eleven_v4_turbo | 18 | 11 | 4 | 33 | research report cut off by queued chat answers; the notes session's answer never spoken (daemon log not kept: cause not read) |
| Anthropic, Soniox | stt-rt-v5 / sonnet / sonnet / haiku / soniox tts-rt-v2 | 18 | 10 | 2 (3 on a rerun) | 30 | research report cut off; two requests not sent in multi; barge-in missed once, then an echoed "Four" heard as the user |
| Gemini only | gemini-3.5-transcribe-live / 3.8-flash / 3.8-flash / flash-lite / 3.8-flash-lite-tts | 14 | 10 | 3 | 27 | replies over the 3.5 s mark (3.8 to 4.7 s); Hebrew "yes" heard as "Ken", so the edit was never approved; the launch date answer refused by the speech check for saying "notes"; no echo guard |
| OpenAI only | gpt-4o-transcribe / gpt-6-sol / gpt-6-sol / gpt-5.6-luna / gpt-4o-mini-tts | 17 | 11 | 1 | 29 | research report cut off; the Hebrew fix never landed (daemon log not kept: cause not read); no echo guard, so its own voice reached the brain |
| Anthropic + ElevenLabs | scribe / sonnet / sonnet / haiku / eleven_v4_turbo | not run | | | | Scribe scored 68.9% intent, the weakest ears |
| None: fully local (`pointe local`), 2026-11-13 | Whisper large-v3-turbo / gemma-4-26b-a4b-it / the same / the same / Kokoro | 10 | not run | not run | 10 of 19 | slow replies (5.8 to 11.6 s against 3.5 to 4 s limits); five brain steps over 8 s; Hebrew answer not spoken in Hebrew; research report not picked up. Every approval check passed. `local.md` |

A Gemini key on the free tier runs out of quota within one run: the first Gemini-only attempt passed 3 of 19 on 429 errors.

## By role

| Role | Measured | Report | Not measured |
|---|---|---|---|
| Ears | Soniox v5, v6; gemini-3.5-transcribe-live; Gemini Live; ElevenLabs scribe; OpenAI (3 models) | `report.txt` | Real speakers (voices are synthetic, `bench/record.py` records your own); phone audio; Soniox v6 endpoint tuning |
| Brain | Sonnet, Opus, Fable, Haiku, gemini-3.8-flash, gemini-4-argon, 11 OpenAI models on current prompts; four local models | `brain_substance.md`, `local.md` | gemini-3.1-pro-preview (smoke test only: steps of 4 to 7.5 s) |
| Reader | The same models | `brain_substance.md` | |
| Gate | Thirteen models | `gate.md` | |
| Mouth | ElevenLabs (5 models), Gemini (2), Soniox, OpenAI | `tts.md` | How a voice sounds to a person (samples in `tts-samples/`) |

Not measured for any setup: a real human call.
