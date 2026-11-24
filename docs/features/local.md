# Fully local

Every model runs on your Mac. No key is read, and nothing Pointe does leaves the Mac: not your speech, not your
sessions, not what the voice says. It costs nothing per hour. It is slower and makes more mistakes than the keyed
setups; the numbers are below, measured on one Mac.

The code is `pointe/local.py` (install, the text-model server, status) and `vendors.local_only` (no key read).

## Use it

```
pointe local          # downloads what is missing, with sizes first, starts the local model, turns the mode on
pointe stop           # then /pointe:voice: the voice restarts on the local models
pointe local status   # what is on disk, whether the model answers, and its memory
pointe local off      # back to the vendors you used before
```

Or from a screen:

- **Voice:** no phrase: it changes which models run, so it is chosen on the Mac and Pointe restarts on it.
- **Page:** on the Mac's own page, Settings → Model keys → "Fully local" → Use this setup. It runs `pointe setup local`
  (the same as `pointe local`: the models download first), then restarts Pointe. A Mac with less than 32 GB is refused
  there, with the reason. A page opened on the phone shows the command only. Settings → Local mode then reads "Fully
  local: on".
- **iPhone app:** no switch: the setup is chosen on the Mac. Settings shows one read-only line while it is on.
- **Mac app:** Settings (••• at the top, or ⌘,) → Model keys → Setup → "Fully local", then Restart under Pointe on this
  Mac.

`/pointe:setup` offers it as "Fully local". `/pointe:doctor` shows the local status in every run.

Needs an Apple-silicon Mac with 32 GB of memory or more, and about 19 GB of disk. Nothing is installed system-wide and
no service is registered: everything sits in your user account.

## What runs

| Role | Local model | Size on disk | License |
|---|---|---|---|
| Ears | Whisper large-v3-turbo, MLX (`mlx-community/whisper-large-v3-turbo`), in the daemon | 1.6 GB | MIT |
| Mouth | Kokoro v1.0 (`kokoro-onnx`), voice `af_heart`, in the daemon | 0.34 GB | Apache-2.0 (model); see GPL note below |
| Brain, reader, gate | Gemma 4 26B A4B instruct, MLX 4-bit (`mlx-community/gemma-4-26b-a4b-it-4bit`), one model for all three | 15.4 GB; 17 GB of memory while it runs | Apache-2.0 |
| Server for the text model | `mlx-lm` 0.32.2, its OpenAI-compatible server on `127.0.0.1:7869`, in its own uv environment under `~/.claude-voice/local/mlx-lm` | 0.4 GB | MIT |

The daemon starts the server when the voice starts and `pointe stop` stops it, so the model's memory is freed when you
are not talking. One model serves the brain, the reader and the gate. Thinking is off in its chat template: with it on,
each reply waits for hidden tokens.

## What stays on the Mac

In fully local mode `vendors.key()` returns nothing for every vendor, from the environment or the Keychain. So no role
can pick a vendor, the Soniox mirror stream (the echo guard) is off, and meeting mode has no ears. A role set to a vendor
in `config.json` or the environment is refused at start, with the command that turns the mode off. Tests:
`tests/test_local.py`.

Answering on `127.0.0.1:7869` is not enough to be trusted with your transcripts: with the server stopped, another
account on the Mac could take the port and answer in its place. Pointe uses the server only when the program
listening there is the one it started (`local/server.pid`) or its child (`local.ours`, through `bin/voice-listeners`);
otherwise `pointe local start` and the daemon's start refuse, and say what to do. The running daemon checks again every
5 seconds (`local.recheck`) and sends no text there until it is that server again; a port taken within those seconds is
the gap. A server you set up yourself and
point `local_url` at (Ollama, say) is yours to vouch for, and is not checked.

What still goes out: model downloads, once, from Hugging Face and GitHub; your coding agents' own traffic, as always.
onnxruntime (the voice detector, the voice lock, kokoro-onnx) connects to Microsoft's telemetry collector when it
loads; Pointe turns that off in every setup (`ORT_DISABLE_TELEMETRY=1`, `pointe/no_telemetry.py`), found while measuring
[Voice stays on your Mac](voice-stays-local.md#measured). The runs above predate it.

## Why these

Each pick is the best of what was measured on this Mac (`bench/results/local.md`):

- **Text model: Gemma 4 26B A4B.** A mixture of experts with about 4B active parameters, so it answers about as fast as a
  small model. It passed the most brain cases (76.9%, against 74.8% for Qwen3.6-35B-A3B and 62.0% for Qwen3.5-9B), with
  the fewest unwanted sends and the shortest p95 reply, in the least memory of the large ones. The first two are inside
  each other's confidence intervals; the smaller memory decided. Qwen3.8-27B, a dense model, took 13 s per reply.
- **Server: mlx-lm.** Apple's own MLX runtime, MIT, installed with uv in a folder of its own: no Homebrew, no system
  service, no app. It keeps the system prompt's cache between turns: a model step on a prompt of about 4,700 tokens
  took 2.1 s at the median. Ollama (since 0.19 also on MLX) works by hand through `local_url`, but it needs its own
  install (Homebrew or its app) and runs its own background server, and nothing measured here shows it faster.
- **Ears: Whisper large-v3-turbo.** It ties full large-v3 on accuracy (p = 0.89) and is 0.3 s faster. The ivrit-ai
  Hebrew fine-tune is the best on Hebrew (95.0%) and mixed speech, but heard English right only 37.5% of the time.
  Parakeet and Qwen3-ASR were not run: neither lists Hebrew.
- **Mouth: Kokoro, as before.** Chatterbox Multilingual (MIT, no eSpeak, claims Hebrew) took 2.4 s to its first English
  audio and its Hebrew was not intelligible. Kokoro on MLX was five times faster than the kokoro-onnx the daemon runs
  (229 against 1283 ms to first English audio) and is the next step, not done here; see Limits.

## Measured

On an Apple M5 Pro with 64 GB, macOS 27.0, 2026-11-13, with other work running on the Mac (load average 17 to 154).
The reports and commands are in [`bench/results/local.md`](../../bench/results/local.md).

| | Fully local | Best keyed (published) |
|---|---|---|
| Brain, 78 cases x 3, pass ignoring length | 76.9% (67.9% to 85.5%) | Sonnet 91.9% (85.9% to 97.0%) |
| Brain, reply p50 / p95 | 3.4 / 9.2 s | Sonnet 1.8 s median |
| Brain, unwanted sends of 234 | 16 (5 refused in code) | Sonnet 9 (all refused in code) |
| Reader, 17 cases x 3, pass | 51.0%, 7.5 s median | Sonnet 100%, 3.8 s |
| Ears, 560 clips, intent right | 85.7%, 0.76 s median | Soniox 95.4%, 0.36 s |
| Mouth, first English audio p50 | 1.28 s (whole reply) | eleven_v4_turbo 0.21 s |
| Single-session audio suite (`tests/e2e/scenarios.py brain`) | 10 of 19 | 18 of 19 (`combinations.md`) |
| Memory while running | 17 GB (text model) | |
| Disk | 17.7 GB of models and server, plus about 0.9 GB of Python packages | |
| Cost | $0 | about $1 a busy hour |

In the audio suite every approval and safety check passed: a delete asked by voice waited for the user, silence
approved nothing, a spoken yes approved and a no denied, and a reconnect replayed nothing. What failed: speed first.
Replies came 7.4 s after the greeting's trigger and 11.6 s after a plain question (which got "one sec" first); side
questions were answered well but in 5.8 to 7.2 s, over the suite's 4 s limit; five brain steps ran past the 8 s limit
("I lost my connection to the model"), so barge-in and a follow-up after a reconnect missed. Then: a Hebrew answer not
spoken in Hebrew, a research report not picked up, and a fix asked in Hebrew that had not landed when checked. The suite's
transcriber and the fake user's voice are cloud services; Pointe used none.

Installing: `pointe local` set up the server's environment in 11 s and had the model answering in 21 s, with the
models already downloaded. A fresh download is 17.3 GB; 1.5 GB took 37 s here, so about 8 minutes on that link.

## Limits

- **It is slower.** A reply takes 3.4 s at the median and 9.2 s at p95 to decide, against 1.8 s for Sonnet; the brain's 8 s
  step limit cuts some off ("I lost my connection to the model"). Add the ears (0.76 s) and the first sentence of
  speech (Kokoro: 1.3 s at the median for an English reply, up to 4.5 s). These were measured with other work on the
  Mac; a quiet Mac should do better, by an amount not measured.
- **It makes more mistakes.** The brain passed 76.9% of cases against 91.9% for Sonnet. It never asked what an unclear
  request meant: it sent it. The gate, the same local model, checks each send against what you said, and approvals keep
  every rule in code, but more wrong requests reach your sessions. Reports pass 51% against 100%.
- **Speech starts late.** kokoro-onnx makes a whole sentence before any of it plays. Kokoro on MLX (mlx-audio) started
  English speech in 229 ms against 1283 ms. It is now in the daemon as `mouth: local:kokoro-mlx`, the mouth of
  [Voice stays on your Mac](voice-stays-local.md); fully local mode does not use it yet.
- **No Hebrew voice.** Kokoro has none: a Hebrew reply is spoken as noise. Speak English with it. Whisper hears Hebrew
  (93.3% of Hebrew clips right).
- **No echo guard.** It needs Soniox's second stream: use headphones.
- **Short answers can be misheard as another language.** Whisper picked a third language for 24 of 120 short clips.
- **GPL in the optional extra.** kokoro-onnx phonemizes with eSpeak NG (GPL-3.0) through `phonemizer`. Every Kokoro
  runtime measured does the same; the permissive option measured (Chatterbox) was too slow. It runs as a library in your
  own environment and is not part of Pointe's source. [THIRD_PARTY.md](../../THIRD_PARTY.md).
- **One Mac.** Measured on an M5 Pro with 64 GB only. A Mac with less than 32 GB is refused; a 9B model that would fit
  passed 62% with 35 unwanted sends, so it is not offered.
- **Not measured:** a real human voice, a quiet Mac, other Apple-silicon generations, and the multi-session and echo
  suites.

## Other machines and servers

`ears: local` and `mouth: local` work on any machine (faster-whisper off Apple silicon). Text models can come from any
OpenAI-compatible server: set `brain`, `reader` and `checker` to `local:<model>` and `local_url` (or
`CLAUDE_VOICE_LOCAL_URL`) to its address, for example Ollama's `http://localhost:11434/v1`. Those setups are not
measured here.
