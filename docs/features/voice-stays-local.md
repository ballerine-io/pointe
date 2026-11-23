# Voice stays on your Mac

Your speech is heard and spoken on your Mac: no audio goes to any vendor. The brain, the reader and the gate stay in the
cloud and get text only. This keeps the measured accuracy of the cloud brain (fully local mode's weak point, by
[measure](local.md#measured)) and keeps your voice off every vendor's servers.

The code is `local.py` (`pointe local voice`), `vendors.voice_local` and `vendors.refuse_cloud_audio` (the guarantee),
and `kokoro_mlx.py` (the mouth).

## Use it

```
pointe key anthropic    # the one key it needs (a Gemini key also works; with both, Gemini runs the gate)
pointe local voice      # downloads Whisper and Kokoro once, turns the setup on
pointe stop             # then /pointe:voice: the voice restarts with local ears and mouth
pointe local off        # back to the vendors you used before
```

Or from a screen:

- **Voice:** no phrase: it changes which vendors run, so it is chosen on the Mac and Pointe restarts on it.
- **Page:** on the Mac's own page, Settings → Model keys → "Voice stays on your Mac" → Use this setup. It runs
  `pointe setup voice-local` (the same as `pointe local voice`: the models download first), then restarts Pointe. A page
  opened on the phone shows the command only. Settings → Local mode then reads "Voice stays on your Mac: on".
- **iPhone app:** no switch: the setup is chosen on the Mac. Settings shows one read-only line while it is on.
- **Mac app:** Settings (••• at the top, or ⌘,) → Model keys → Setup → "Voice stays on your Mac", then Restart under
  Pointe on this Mac.

`/pointe:setup` offers it as "Voice stays on your Mac". `pointe doctor` names it, lists which vendors get text, and shows
Soniox and ElevenLabs as "not read". Needs an Apple-silicon Mac (Whisper and the voice run on MLX) and about 3 GB of
disk (2.0 GB of models, 1.1 GB of local libraries); memory is not a limit, as no text model runs here.

## What runs where

| Role | Where | Model |
|---|---|---|
| Ears | this Mac | Whisper large-v3-turbo on MLX (`mlx-community/whisper-large-v3-turbo`), MIT |
| Mouth | this Mac | Kokoro-82M on MLX (`mlx-community/Kokoro-82M-bf16`, mlx-audio 0.6.5), voice `af_heart`, Apache-2.0 |
| Brain, reader | Anthropic (or Gemini, OpenAI) | `claude-sonnet-5-5`, as in the default setup |
| Gate | Gemini if its key exists, else the brain's vendor | `gemini-3.5-flash-lite`, else `claude-haiku-5-5` |
| Echo guard | this Mac | the bot's own text against what Whisper heard; no mirror stream |
| Meeting mode | off | telling speakers apart needs Soniox's cloud stream, and no local model does it yet |
| Voice lock | this Mac | as in every setup |

## What leaves the Mac, exactly

- **To the brain and reader vendor (Anthropic):** what you said, as text (Whisper's transcript); session content
  (transcripts, notes, reports, briefings); what the bot says, as text.
- **To the gate vendor (Gemini, if its key exists):** what you said, as text, each session's latest lines, goal, folder
  path and up to 40 file names. The same as in every keyed setup.
- **Never:** audio of any kind: your microphone, the bot's voice, the room. Not the voiceprint. Not onnxruntime's
  telemetry, which Pointe turns off in every setup (see Measured).
- **Once:** model downloads from Hugging Face (and the spaCy English model from GitHub, when uv installs it).
- **Phone:** with the iPhone app, its audio crosses your own paired link (Tailscale, Twingate or Wi-Fi, TLS with a
  pinned certificate) to the Mac. That carries audio between your devices; no vendor transcribes or stores it.

## The guarantee, in code

With the setup on (`"voice_local": true` in `config.json`, or `CLAUDE_VOICE_VOICE_LOCAL=1`):

- The Soniox and ElevenLabs keys are never read, from the environment or the Keychain: their only use here is audio.
- Ears and mouth resolve to local. A cloud ear or mouth set in `config.json` or the environment stops the daemon at
  start, with the command that turns the setup off. It never falls back to a cloud audio vendor.
- `build_ears` and `build_mouth` refuse every vendor but local; a realtime front (`CLAUDE_VOICE_FRONT=gemini|openai`)
  and `CLAUDE_VOICE_EARS=native`, where a model hears the audio, are refused.
- The echo guard's mirror stream and meeting ears, the two other paths that stream audio to Soniox, call
  `vendors.refuse_cloud_audio` before connecting, and are not built in the first place.
- Fully local mode (`pointe local`) implies all of this.

`tests/test_voice_local.py` checks it offline: with every vendor's key present, constructing any cloud speech client
(Soniox, Gemini, OpenAI, ElevenLabs; STT, TTS and realtime) or opening any WebSocket fails the test, and the whole call's
ears, mirror and mouth must still build. Removing either guard turns it red (checked).

## Echo

The default setup's echo guard compares what the ears heard with a second Soniox stream of the bot's own voice. Here
there is no second stream: the guard compares Whisper's transcript with the text the bot was given to say, normalized the
same way (numbers, file names, symbols). Whisper writes the bot's words close to how they were written, and that holds
for keeping the bot's own voice out; it does not make interrupting it fast.

The echo suite (`tests/e2e/echo.py`: the bot's voice fed back into the microphone at half volume, no echo cancellation),
five runs: the story played to the end over its own echo every time, and its echo never reached the brain (about 20 echo
transcripts dropped per run). The check "the echo never reaches the model as the user" still failed every run, on the
user's own request: Whisper split "Tell me a story ... / about eight sentences long" into two segments, and the check
expects one. A spoken "Stop. What is two plus two?" over the story stopped it and was answered "Four" in four runs, but
Whisper transcribes a segment only once it closes, so the cut came 3 to 4 s after the user began: inside the suite's
window once (3 of 4), outside it three times (1 of 4). In the other run Anthropic answered 503 ("credential validation
failed") for the second story, so there was nothing to interrupt (1 of 4). With headphones there is no echo floor and a voice cuts in at once
(0.39 s in the single-session suite).

So: **use headphones**, or expect a spoken interruption to take a few seconds on speakers. A faster local cut-in would
need Whisper passes over the open segment while the bot talks; it is not built.

## Measured

On an Apple M5 Pro with 64 GB, macOS 27.0, 2026-11-13, with other work running on the Mac (load average about 10 to 14).
Keys visible to the daemon: Anthropic and Gemini only (a test-only `security` shim refused every other Keychain item),
on isolated ports and state. The default cloud setup's numbers are from the same suites on the same day
([combinations.md](../../bench/results/combinations.md)).

| | Voice stays on your Mac | Default cloud setup (Soniox, Anthropic, Gemini, ElevenLabs) |
|---|---|---|
| Audio suites, `tests/e2e/run_all.sh` (single / multi / echo) | **30 of 35** (16 / 11 / 3) | 34 of 35 (18 / 12 / 4) |
| Single-session suite again, its daemon alone on the Mac | 15 of 19 | |
| Reply latency in the single-session suite, end of speech to first audio, median of 6 replies | 4.1 s alone (2.5 to 5.0); 4.2 s with three daemons (3.1 to 11.1) | 2.4 s (2.0 to 2.6) |
| Mouth, first English audio, `bench/local_tts_bench.py` (24 clips x 3) | **185 ms** p50, 233 ms p95 (kokoro-onnx: 750 / 915 ms in the same run) | 213 ms (`eleven_v4_turbo`, `tts.md`) |
| Mouth, time to first audio inside the live calls (37 sentences) | 0.36 s p50, 1.5 s p90 | |
| Ears, 560 clips, intent right, same run and judge (`bench/stt_extra.py`) | 82.7% (79.5 to 85.5) | Soniox 94.6% (92.7 to 96.4); p = 6e-14 |
| Ears by kind: English / Hebrew / mixed / short yes-no | 85.0% / 91.7% / 70.0% / 87.5% | |
| Ears latency p50 / p90 (voice detector wait plus transcription) | 0.61 / 0.69 s | Soniox 0.33 / 0.58 s |
| A busy hour (arithmetic, `docs/benchmarks.md`) | about $0.40 | about $1 |

Where the reply time goes, for the plain question run alone: the voice detector closed the segment, Whisper wrote it
in 0.34 s, the brain took 2.6 s, and Kokoro took 1.6 s to start a long first sentence. Speech from Kokoro starts on a
whole sentence, so a long one waits longer; the median sentence started in 0.36 s.

Failures (both runs): the plain question was over the suite's 3.5 s limit (5.0 s alone; 11.1 s with three daemons
sharing the GPU); the Hebrew answer was spoken as Hebrew letter names (the parallel run's check counted it as passed:
29 of 35 in substance); the fix asked in Hebrew had not landed when checked; after a reconnect it did not say what the
session had done. Multi-session: the second session's answer was not reported. Echo: see above. Every approval and
safety check passed in both runs.

The ears row from fully local mode's day ([local.md](../../bench/results/local.md)) read 85.7% for the same model; this
run's 82.7% used the same clips and judge model, with the judge's verdicts made again. The two runs' intervals overlap.
Whisper turbo's Hebrew is good on Hebrew alone and weak when Hebrew and English mix in one sentence (70.0%, against 90.6% for Soniox in
the same run).

What the daemons connected to during the suites, by sampling their sockets every second: Anthropic
(`160.79.104.10`), Google (`172.217.x`, the Gemini gate), and Microsoft's telemetry collector
(`*.events.data.microsoft.com`). The last is `onnxruntime` 1.31, which runs the voice detector (Silero) in every setup:
it connects on import, from native code, so Python's own socket hooks never saw it. Its content was not inspected. Pointe
now sets `ORT_DISABLE_TELEMETRY=1` before onnxruntime can load, in every setup (`no_telemetry.py`, imported first by every
module that can reach it, and exported by the launchers), which stopped the connection in isolation and in a rerun of the
echo suite (only Anthropic connected; the Gemini gate had nothing to check). `tests/test_no_telemetry.py` fails if any
module reaches onnxruntime without it.

## Why these

- **Mouth: Kokoro on MLX, voice `af_heart`.** The same Kokoro weights as fully local mode's kokoro-onnx, run on the
  GPU: English speech starts in 185 ms at the median, against 750 ms for kokoro-onnx in the same run. `af_heart` is the only voice Kokoro's own card grades A. Seven candidate voices were rendered with
  the same passage; all were heard back by Whisper word for word, so intelligibility does not separate them. How they
  sound is for a person to judge: `uv run --locked --extra local python -I bench/local_tts_bench.py voices` writes them to
  `bench/.audio/voice-samples/`.
- **Ears: Whisper large-v3-turbo**, as in fully local mode ([why](local.md#why-these)).
- **Brain in the cloud.** The local brain was fully local mode's bottleneck: 76.9% of cases against 91.9% for Sonnet,
  with replies of 3.4 s against 1.8 s at the median.

## Limits

- **No Hebrew voice.** Kokoro has none, and the brain answers in the language you spoke: a Hebrew reply is spoken as
  Hebrew letter names. Speak English with it. Whisper hears Hebrew (91.7% of Hebrew clips right).
- **On speakers, interrupting takes 3 to 4 s** (see Echo). Use headphones.
- **The ears are weaker than Soniox:** 82.7% of intents against 94.6% (p = 6e-14), and 70.0% on mixed Hebrew and
  English. Short answers can be heard as another language.
- **Slow starts when the GPU is shared.** With three voice daemons on one Mac (the parallel suites), the mouth took 4 to 8 s
  to start for each daemon's first minute; alone it started in 0.36 s at the median and 1.5 s at p90. Kokoro's first sentence after the daemon starts
  builds its pipeline (about 5 s, logged as "local mouth ready"); the daemon does this at start.
- **No meeting mode:** it needs Soniox's speaker labels.
- **eSpeak NG (GPL-3.0)** comes with the optional `local` extra, as for fully local mode ([THIRD_PARTY.md](../../THIRD_PARTY.md)).
- **Apple silicon only**, measured on one M5 Pro with 64 GB, with other work running (load average about 10 to 14).
- **Not measured:** a real human voice; a quiet Mac; other Macs.
