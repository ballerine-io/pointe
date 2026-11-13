# Which vendors are covered, 2026-11-13

Each role is benchmarked on its own; a whole setup is then checked by the real audio suite (`tests/e2e/run_all.sh`), with each role set by `CLAUDE_VOICE_*`.

## Whole setups, real audio

2026-11-13, the current code (WebSocket call, 19 single-session checks, 12 multi-session, 4 echo at speaker gain 0.5). One run each;
only the listed keys were visible to the daemon (a test-only `security` shim on `PATH` refused the other Keychain items), and the
Gemini key was the paid one. Counts are passes of 35; the single-session suite counts a skipped check as passed, as it did on 2026-11-08.

| Keys | Ears / brain / reader / gate / mouth | Single | Multi | Echo | Total | 2026-11-08 | Failures, from the suite and daemon logs |
|---|---|---|---|---|---|---|---|
| Soniox, Anthropic, Gemini, ElevenLabs (default) | stt-rt-v5 / sonnet / sonnet / flash-lite / eleven_v4_turbo | 18 | 12 | 4 | 34 | 33 | research report not picked up: the bot came back to the earlier notes2.txt answer instead |
| Anthropic, Soniox | stt-rt-v5 / sonnet / sonnet / haiku / soniox tts-rt-v2 | 19 | 8 (9 on a rerun) | 3 | 30 (31) | 30 | run 1: the test's call socket dropped mid-suite, so the last four multi checks failed together; the rerun failed on its own: the session list answer did not name both, an unnamed request went to the wrong session (routing: thread), a by-the-way question got no answer. Echo: after the barge-in the bot kept telling the story |
| Gemini only | gemini-3.5-transcribe-live / 3.8-flash / 3.8-flash / flash-lite / 3.8-flash-lite-tts | 17 | 11 | 0 | 28 | 27 | replies over the 3.5 s mark (4.0 to 4.5 s); the launch date answer was spoken (daemon log) but the check heard none of it; no echo guard: its own "One sec." reached the brain as the user, and the user's "Stop" did not cut in |
| OpenAI only | gpt-4o-transcribe / gpt-6-sol / gpt-6-sol / gpt-5.6-luna / gpt-4o-mini-tts | 15 | 9 | 0 | 24 | 29 | the scratch-file request was never sent while the README delete waited for a typed approval, so the two voice-approval checks had nothing to approve; research report not picked up; the Hebrew fix never landed; multi: session list cut short, the notes answer not reported, a by-the-way question unanswered; no echo guard |
| Anthropic + ElevenLabs | scribe / sonnet / sonnet / haiku / eleven_v4_turbo | not run | | | | | Scribe scored 68.9% intent, the weakest ears |
| None: fully local (`pointe local`), 2026-11-13 | Whisper large-v3-turbo / gemma-4-26b-a4b-it / the same / the same / Kokoro | 10 | not run | not run | 10 of 19 | — | slow replies (5.8 to 11.6 s against 3.5 to 4 s limits); five brain steps over 8 s; Hebrew answer not spoken in Hebrew; research report not picked up. Every approval check passed. `local.md` |

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
