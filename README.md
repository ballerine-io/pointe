<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/logo-on-dark.svg">
    <img src="docs/brand/logo.svg" width="112" height="112" alt="The Pointe mark: one orange point and rings of dots around it">
  </picture>
</p>

# Pointe

A conversational layer for your coding agents. Built and open-sourced by Ballerine Engineering.

Talk to all your coding-agent sessions by voice. Ask what each one did, switch by saying its name, and answer
permission prompts out loud, from across the room, under rules enforced in code.

Pointe is one voice that knows every session you join to it. The sessions do the work and keep their context; Pointe
listens, reports, routes your requests, and reads approvals out. It works with Claude Code, OpenCode and Codex. It runs
on your Mac, with no server and no account: you bring the model keys, or run models locally.

```
You:     What is the payments session doing?
Pointe:  It finished the retry fix. Tests pass. It wants to know if it should open the PR.
You:     Yes. And tell the docs session to update the changelog.
Pointe:  Docs is on it.
You:     By the way, why did payments drop the queue idea?
Pointe:  Duplicate charges during failover. It decided that an hour ago.
```

- **Hands-free across sessions.** One conversation over every session you joined, with a live transcript on the page and
  in the iPhone app.
- **Strict approvals.** A spoken yes approves only a request the daemon read out itself from what will run, and only
  right after it. Anything it cannot read out waits for a tap. A no from any voice denies.
- **Any harness.** [Claude Code](https://code.claude.com), [OpenCode](https://opencode.ai) (v2) and
  [Codex CLI](https://github.com/openai/codex) (started as `codex --remote unix://`), side by side in one call.
- **Your keys, or none.** You pay the vendors directly. Or run `pointe local`: every model on your Mac, no key, nothing
  sent out, with its measured cost in speed and accuracy. [docs/features/local.md](docs/features/local.md).

## Install

You need macOS, [Claude Code](https://code.claude.com) 2.1.224 or newer, Chrome, headphones, and API keys from one or
two model vendors, or an Apple-silicon Mac with 32 GB of memory for the fully local mode. The cheapest start is one
Google AI Studio key, which has a free tier: [Try it for free or cheap](#try-it-for-free-or-cheap).

**What do I need?** Any one of these is enough to start: (a) one Gemini key (free tier; about $0.70 to $0.95 a busy
hour with billing on), (b) one OpenAI key (about $0.95 a busy hour), (c) Soniox + Anthropic API keys (about $1.20).
Fastest and most accurate voice: Anthropic + Soniox + ElevenLabs (+ Gemini for the checker), about $1 a busy hour.

Why its own keys? Pointe runs its own models next to Claude Code: the brain, the reader and the checker, the ears and
the voice. Your Claude subscription (Pro or Max) runs Claude Code, but has no interface other apps can use, so
Pointe's voice needs its own API key from console.anthropic.com, or one Gemini key. An API key is billed per use:
about $1 for a busy hour of talk.

<!-- setups: written by tools/setups.py from setups.py -->
| Setup (`pointe setup <id>`) | Keys | Measured | A busy hour | Pick it for |
|---|---|---|---|---|
| Free start (`free`) | Gemini | 28 of 35 audio checks on a paid key; a free-tier key ran out of quota in the run (3 of 19); replies took 4.0 to 4.5 s | $0 until the free quota ends; about $0.70 to $0.95 with billing on | just trying it; no budget |
| One OpenAI key (`openai`) | OpenAI | 24 of 35 audio checks; whole replies not measured; the brain answers in 2.4 s at the median | about $0.95 | you already pay for OpenAI |
| Two keys (`two`) | Soniox + Anthropic | 30 of 35 audio checks (31 on a rerun); echo guard 3 of 4, so speakers work; whole replies not measured; the brain answers in 1.8 s at the median, the voice starts in 301 ms | about $1.20 | the best ears with two accounts; laptop speakers |
| Fastest and most accurate voice (`full`) | Anthropic + Soniox + ElevenLabs + Gemini | 34 of 35 audio checks, echo guard 4 of 4: the highest whole-setup result; replies in 2.4 s at the median (2.0 to 2.6), the fastest measured | about $1 | daily use |
| Voice stays on your Mac (`voice-local`) | Anthropic (Gemini optional) | 30 of 35 audio checks, with Anthropic and Gemini keys; replies in 4.1 s at the median | about $0.40 (Anthropic and Gemini) | confidential work where text may leave the Mac but your voice may not |
| Fully local (`local`) | none | 10 of 19 one-session audio checks, every approval check among them; replies took 5.8 to 11.6 s | $0 | nothing may leave the Mac; no budget with a 32 GB Mac |

Sources, speed and where your words go: [docs/setups.md](docs/setups.md).
<!-- end setups -->

```
claude plugin marketplace add https://github.com/ballerine-io/pointe.git && claude plugin install pointe@pointe
```

Start a new Claude Code session and run `/pointe:setup`. It checks your Mac, installs [uv](https://docs.astral.sh/uv/)
if it is missing, helps you choose vendors (with measured quality and cost), stores each key in the macOS Keychain
through a Mac window (never in the chat), starts your first call, and can pair your phone. More options, including the
Claude desktop app: [docs/install.md](docs/install.md).

Then, in each session you want to reach:

```
/pointe:voice
```

The first run downloads about 180 MB. A tab opens: allow the microphone, press Connect, and talk.

**The Mac and iPhone apps** are optional, and built from source until there is a download. With Xcode installed, from a
clone of this repository: `bin/pointe apps doctor` says what is missing, `bin/pointe apps mac` builds the Mac app and
puts it in `~/Applications`, and `bin/pointe apps ios` builds the iPhone app, signs it with your (free) Apple Account
and installs it on your iPhone. [The Mac app](docs/mac-app.md#getting-it), [the iPhone app](docs/phone.md#getting-the-app).

| Command | Does |
|---|---|
| `/pointe:setup` | guided setup: keys, first call, phone |
| `/pointe:voice` | join this session to the voice (starts the daemon if needed) |
| `/pointe:open` | open the page again |
| `/pointe:leave` | take this session off the voice (or say "close billing" or "close all except billing", or use × on the page) |
| `/pointe:stop` | stop all voice |
| `/pointe:doctor` | what runs here, what is missing, and the one key that would help most |
| `pointe local` | fully local: download and start the local models, no keys ([details](docs/features/local.md)) |
| `pointe local voice` | voice stays on your Mac: local ears and mouth, the brain in the cloud gets text only ([details](docs/features/voice-stays-local.md)) |
| `/pointe:voice-review` | ask a session what happened in the last call |

OpenCode and Codex sessions join with `pointe join opencode` or `pointe join codex`: see
[docs/harnesses.md](docs/harnesses.md).

Pointe can also start a session for you, in a folder you already work in: say "start a new Codex session in shop", or
use New session on the page or in the apps. It reads back what it will start and waits for your yes:
[docs/features/new-session.md](docs/features/new-session.md).

### Try it for free or cheap

- **Free:** one [Google AI Studio](https://aistudio.google.com/apikey) key, no card. Google lists every model Pointe
  uses with it as free of charge on its free tier (read 2026-11-19). The quota is small and unpublished: a free key ran
  out during one of our test runs. Google may use and review what you send on that tier, so try it on a project you
  could publish.
- **One paid key:** the same key with billing on, about $0.70 to $0.95 for a busy hour of talk.
- **No audio leaves the Mac, on any Apple-silicon Mac:** `pointe local voice` with one text key, about $0.30 to
  $0.40 a busy hour. It runs no text model, so it has no memory floor; it was not measured on a 16 GB Mac. Fully
  local mode needs 32 GB: a model small enough for 16 GB was measured and is not offered.

The table, the sources and the limits: [docs/install.md](docs/install.md#try-it-for-free-or-cheap).

## What it does

**The core**

- **One voice over many sessions.** Say a session's name to talk to it or switch to it. Background sessions stay quiet
  except for "finished" or "needs approval". Ask "by the way" questions: they are answered from a read-only copy, so the
  live session is never interrupted.
- **Session notes.** A reading model keeps each session's goal, state, decisions, what was ruled out and what is open,
  and turns each final message into what you need to hear. [How it works](docs/how-it-works.md).
- **Live transcript.** The page shows the conversation as it happens, the exact text of every pending request with
  Approve and Deny, and lets you type or correct what was heard.
- **Mac app.** The call in the menu bar and a native window with everything the page and the iPhone app have, on the
  iPhone app's own screens, and a system-wide talk shortcut. Built from source for now, with one command:
  `bin/pointe apps mac`. [docs/mac-app.md](docs/mac-app.md).
- **iPhone app.** The same call and controls on your phone, paired once by QR code over Tailscale, a VPN such as
  Twingate, or Wi-Fi. Approve needs Face ID. Built from source for now: `bin/pointe apps ios`, with a free Apple
  Account. [docs/phone.md](docs/phone.md#getting-the-app).
- **Several harnesses and accounts** in one call, each session with its own approvals. [docs/harnesses.md](docs/harnesses.md).

**Features** (each page says how to use it, the rules, what was measured, and the limits)

| | |
|---|---|
| [Start a new session](docs/features/new-session.md) | "Start a Codex session in shop": read back, started on your yes, only in folders you already work in, never with prompts skipped. |
| [Machines](docs/multi-machine.md) | Sessions on your other Macs and Linux machines join the same voice, each shown with its machine. |
| [Voice lock](docs/features/voice-lock.md) | Only your voice counts, for approvals or for everything. Checked on this Mac. |
| [Self-learning vocabulary](docs/features/vocabulary.md) | Fix a misheard name once, and the next call hears it right. |
| [Drive & walk mode](docs/features/drive-mode.md) | Short answers, nothing to look at, and only requests that lose nothing approved by voice. |
| [Push to talk](docs/features/push-to-talk.md) | No audio leaves the Mac unless you hold the key or the button; a system-wide shortcut talks from any app. |
| [Audio briefings](docs/features/briefings.md) | "Brief me on the night": what each session did, failed and waits on. |
| [Challenge me](docs/features/challenge.md) | The voice argues against your plan, grounded in your sessions, and cannot send. |
| [Wrist approvals and desktop alerts](docs/features/alerts.md) | A session needs you: the watch taps, the desktop notifies. |
| [Show while it says](docs/features/show-while-it-says.md) | The file, diff or failing test appears on screen as the voice mentions it. |
| [Whisper mode](docs/features/whisper-mode.md) | Quiet replies and a raised microphone, with the same approval rules. |
| [Conflict alarm](docs/features/conflict-alarm.md) | Two sessions claim opposite things about the same work: you hear it at once. |
| [Meeting mode](docs/features/meeting-mode.md) | Notes, lookups and a raised hand in a meeting, with consent and no sends. |
| [Voice stays on your Mac](docs/features/voice-stays-local.md) | Ears and mouth on your Mac, so no audio goes to any vendor; the cloud brain gets text only. |
| [Fully local](docs/features/local.md) | Every model on your Mac, no keys, nothing sent out; slower and less accurate, by measure. |

## Compared to

Other tools cover parts of this, and several do more than Pointe in their own area. Each line was read at the
project's own docs or source on 2026-11-19; these products change, so follow the link before you rely on it.

| | What it is | Voice | Approving by voice |
|---|---|---|---|
| [Happy](https://github.com/slopus/happy) (MIT) | Phone, web and desktop clients for Claude Code, Codex and other agents, started through its `happy` command, over an end-to-end encrypted relay you can host yourself | A voice assistant across your sessions, on ElevenLabs | Yes: "It reads permission requests out loud. It allows or denies one only when you say so, unless you tell it to accept the ones that follow." ([docs](https://happy.engineering/docs/features/voice-coding-with-claude-code)) |
| [Paseo](https://github.com/getpaseo/paseo) (open source) | A local daemon with desktop, iOS, Android, web and CLI clients for many agents, direct or over an optional encrypted relay | Dictation, and a voice mode; speech runs on the device by default ([docs](https://github.com/getpaseo/paseo/blob/main/public-docs/voice.md)) | Not described in its voice docs |
| [Claude Code `/voice`](https://code.claude.com/docs/en/voice-dictation) | Dictation built into Claude Code | Your speech becomes text in the prompt; the docs describe no spoken reply | No |
| [Codex voice](https://learn.chatgpt.com/docs/features/voice) | Voice built into the Codex CLI (`/voice`, on by default since [0.156.0](https://github.com/openai/codex/releases/tag/rust-v0.156.0)) and the ChatGPT desktop app | A spoken conversation that can start tasks, check them and switch between them | The docs say voice "follows the same permissions as the tasks it directs" and describe no spoken approval |
| [Claude Code Remote Control](https://code.claude.com/docs/en/remote-control) | A session on your machine, continued from claude.ai/code or the Claude phone app | None described | No |
| [Moshi](https://getmoshi.app/) | A phone terminal over SSH or Mosh, with hooks that bring agents' approvals to the lock screen and the watch | On-device dictation into the terminal | No: a tap |
| [Omnara](https://github.com/omnara-ai/omnara) (Apache-2.0) | A platform that runs agents on managed or self-hosted machines | None named in its README | No |

**Happy is the closest, and it is ahead in several ways.** It has apps in the App Store and on Google Play, it runs on
Android, Windows and Linux, it supports more agents, and it is widely used (about 24,700 GitHub stars). Its voice is free for 20 minutes every
30 days, then a subscription, or your own ElevenLabs agent.

Where Pointe differs from Happy:

- **Code decides what a spoken yes approves.** Pointe's daemon reads a request out itself, from the command that will
  run, only if every part of it is on an allowlist, and takes a plain yes only right after that read-out; anything else
  waits for a tap ([Safety model](#safety-model)). In Happy's Android source the voice model allows or denies through a
  tool call, under a prompt rule to wait for the user
  ([`VoiceTools.kt`](https://github.com/slopus/happy/blob/main/packages/happy-android/app/src/main/kotlin/com/slopus/happy/voice/VoiceTools.kt),
  [`VoicePrompts.kt`](https://github.com/slopus/happy/blob/main/packages/happy-android/app/src/main/kotlin/com/slopus/happy/voice/VoicePrompts.kt));
  we did not read its other clients.
- **No relay and no account.** The call is between your browser or phone and a daemon on your Mac. Happy's relay
  carries encrypted messages between your devices, and its voice sends audio, the session list, recent messages and
  permission requests to ElevenLabs.
- **You choose each model, or run them on the Mac.** Three or four vendors for each role, two local modes, and no metered voice minutes.
- **It joins sessions that are already running**, with `/pointe:voice`, and they keep their context. It can also start a new one, on your yes.

**The built-in voices** need nothing installed and work on Linux and Windows too. Claude Code's `/voice` is for
dictating a prompt and needs a Claude.ai sign-in. Codex voice is a full spoken conversation over Codex tasks; in the
desktop app it needs a paid ChatGPT plan. Pointe is one conversation over Claude Code, OpenCode and Codex sessions together, on your own
keys. Dictation and Pointe work side by side.

**The phone remotes** (Remote Control, Moshi, Paseo, Happy) reach your sessions from anywhere with store apps. Pointe's
iPhone app is built from source for now and reaches the Mac only over a network you set up.

## Safety model

Words you speak can make a session do work, so the rules are in code with tests, not in a prompt. The whole threat
model, including what Pointe does not defend against, is in [SECURITY.md](SECURITY.md).

**What can approve a permission prompt**

- **Your spoken yes**, only when all of these hold: the daemon read the request out itself, from what will run (not
  from the model's description); it was the last thing the bot said; you said a plain yes and nothing else, begun after
  the read-out ended, within 120 seconds, on the active session. "Okay, tell me more", "yes, and run the linter", silence,
  and a yes to any other question approve nothing. An echo of the bot's own voice never counts.
- **A tap** on the exact request, on the page or in the iPhone app (Face ID). A request the daemon cannot read out
  whole (unknown programs or flags, `$`, globs, subshells, several lines, `sudo`, more than 25 words) is approved only
  this way. In our own Claude Code history, about 13% of shell commands can be read out.
- **The terminal**, as always. Your Claude Code deny rules still apply. Set `"approvals": "terminal"` in
  `~/.claude-voice/config.json` to keep every prompt there.
- **A notification's Approve**, only if you turn it on, and only for a request that could be read out.

**What never approves**

- **Typed words.** Text typed or corrected in the call never approves. When a session will accept an approval only
  typed in its own terminal, Pointe refuses to relay a yes to it and tells you to type it.
- **A voice match.** The [voice lock](docs/features/voice-lock.md) only narrows: it adds "and it was your voice", and a
  match is never consent.
- **A mode.** Drive, whisper, meeting, briefing and challenge modes can only narrow what a word may do. In a meeting,
  nothing is approved or sent by voice.

**Always**

- **A no from any voice denies** a pending request, in every mode.
- **Secrets are never spoken.** A credential-like value (a key, a token, `password=`) is never read out, shown in a
  notification, or put in a briefing; such a request waits for a tap. Values are masked in what the screen shows too.
- **Session output is data, not instructions.** A model gate checks each send against what you just said. It lowers the
  risk of prompt injection; it does not remove it.
- **Voice is not authentication.** Anyone your microphone hears can say no, and, with the voice lock off, yes. A
  recording of your voice can pass the lock. Do not use voice approvals in a room you do not trust.

The daemon listens on loopback only, every route needs a secret, and `Origin` must match `Host`. Phone access is a
separate, opt-in TLS listener with a pinned certificate.

## Privacy

Pointe has no server and no telemetry (its libraries' telemetry is turned off too: [SECURITY.md](SECURITY.md)), and the page loads nothing from outside your Mac. What leaves the Mac goes to the
vendors you chose, under your keys:

| What | Goes to |
|---|---|
| Your speech, plus hints: your dictionary, session and folder names, names from session notes | the ears vendor (Soniox, Google Gemini, OpenAI or ElevenLabs) |
| Session content: transcripts, notes, reports, briefings, conflict checks | the brain and reader vendors (Anthropic, Google Gemini or OpenAI) |
| What the bot says, which can quote session content | the mouth vendor (ElevenLabs, Google Gemini, Soniox or OpenAI) |
| What you said, each session's latest lines, goal, folder path and up to 40 file names | the gate vendor |
| In a meeting you started: the room's audio, and transcript windows | Soniox, and the reader vendor |

With "Voice stays on your Mac" (`pointe local voice`), the first and third rows stay on the Mac: Whisper hears and Kokoro
speaks here, the Soniox and ElevenLabs keys are never read, meeting mode is off, and the daemon refuses any cloud audio
path in code. Your words reach the brain, reader and gate vendors as text.

Stays on the Mac: your voiceprint and the audio scored against it, the call journal, session notes, the dictionary,
briefings, meeting transcripts (in memory unless you export them), and the files shown on screen. The phone reaches
the daemon only over your own paired link. Keys come from the environment or the macOS Keychain and reach the daemon only.

With push to talk on, no audio leaves the Mac unless you hold the talk control (plus 0.4 s after release); the daemon
enforces this whatever a client sends. In fully local mode (`pointe local`), no key is read, so no model vendor is used
at all. The full list of
files and what they hold: [SECURITY.md](SECURITY.md#files).

## Models and cost

Each role is separate. Set any of them in `~/.claude-voice/config.json`, or with `CLAUDE_VOICE_<ROLE>` (the environment
wins). A role you do not set takes the first vendor with a key.

| Role | Does | Default (why: [docs/benchmarks.md](docs/benchmarks.md)) |
|---|---|---|
| `ears` | speech to text | `soniox` |
| `brain` | understands you and replies | `anthropic:claude-sonnet-5-5` |
| `reader` | turns session output into short reports | `anthropic:claude-sonnet-5-5` |
| `checker` | a safety check on each send and approval | `gemini:gemini-3.5-flash-lite` |
| `mouth` | the voice | `elevenlabs:eleven_v4_turbo` |

The defaults are the first vendor with a key; a chosen setup (`pointe setup <id>`) uses only its own vendors. Each
setup's measured result, speed, cost and where your words go, with the file and row of every number:
[docs/setups.md](docs/setups.md). `bin/voice-doctor` tells you which setup you are on.

**Fully local:** `pointe local` downloads and starts Whisper (ears), Kokoro (mouth) and Gemma 4 26B A4B (brain,
reader and gate) on this Mac, and reads no key. On an M5 Pro with 64 GB, the brain passed 76.9% of 78 cases (Sonnet
91.9%) and decided in 3.4 s at the median (Sonnet 1.8 s), the ears got 85.7% of intents (Soniox 95.4%), and 10 of 19
single-session audio checks passed, every approval check among them. It has no Hebrew voice. It needs 32 GB of memory
and about 19 GB of disk. [docs/features/local.md](docs/features/local.md).

On macOS, keep keys in the Keychain: `pointe key <vendor>` opens a window for it.

## Benchmarks

The defaults come from benchmarks in `bench/`, all on synthetic data; re-run them with your own keys. Summary from
[docs/benchmarks.md](docs/benchmarks.md):

- **Ears:** 560 clips (English, Hebrew, mixed, short yes/no; 4 voices; clean and noisy). Soniox stt-rt-v6, what runs
  since Soniox removes v5 on 2026-12-15, got intent right 95.9% of the time, word error 0.063, latency p50 0.38 s; v5 had
  95.4% and 0.36 s. v6 held some turns about 3 s; Pointe asks it for the words after a silence, which brings the p90
  to 0.76 s (Hebrew 0.80 s).
  [`bench/results/report.txt`](bench/results/report.txt), [`bench/results/soniox-v6.md`](bench/results/soniox-v6.md)
- **Brain:** 78 cases on the real tool and speech path. `claude-sonnet-5-5` passes 91.9% with a 1.8 s median reply;
  `gemini-3.8-flash` 94.9% at 2.7 s; the confidence intervals overlap. [`bench/results/brain.md`](bench/results/brain.md)
- **Gate:** 24 cases, two runs per model; `gemini-3.5-flash-lite` failed none. [`bench/results/gate.md`](bench/results/gate.md)
- **Mouth:** `eleven_v4_turbo` first audio 213 ms p50, word error 0.00 English, 0.02 Hebrew.
  [`bench/results/tts.md`](bench/results/tts.md)
- **Voice lock:** equal error rate 1.9% on sentences, 2.7% on short answers, on 19 synthetic voices.
  [`bench/results/speaker.md`](bench/results/speaker.md)
- **Vocabulary:** a misheard name spelled right 25 of 64 times without hints, 60 of 64 with them.
  [`bench/results/vocab.md`](bench/results/vocab.md)
- **Challenge me:** 15/30 to 30/30 on Sonnet, 21/30 to 30/30 on Gemini Flash. [`bench/results/challenge.md`](bench/results/challenge.md)
- **Whisper:** Soniox word error 1.4% on a synthetic whisper at -18 dB, 18.4% at -30 dB. [`bench/results/whisper.md`](bench/results/whisper.md)
- **Fully local**, on an M5 Pro: brain 76.9% with a 3.4 s median reply, reader 51.0%, ears 85.7% intent at 0.76 s,
  Kokoro's first English audio 1.3 s, 10 of 19 single-session audio checks. [`bench/results/local.md`](bench/results/local.md)
- **Voice stays on your Mac**, on an M5 Pro: Kokoro on MLX starts English speech in 185 ms at the median (kokoro-onnx 750 ms,
  ElevenLabs 213 ms); Whisper large-v3-turbo got 82.7% of intents in the same run as Soniox's 94.6%; 30 of 35 audio checks.
  [docs/features/voice-stays-local.md](docs/features/voice-stays-local.md)
- **Which setups were tested end to end:** [`bench/results/combinations.md`](bench/results/combinations.md)

Not measured for any setup: a real human voice on a real call.

## Architecture

```
 Chrome page, Mac app (loopback)  iPhone app (paired TLS, pinned)
          \                               /
           one WebSocket per call: audio both ways, plus status and taps
                              |
   daemon on your Mac, the hub (Python, Pipecat)
     ears -> echo guard -> brain (tools; speech is a tool call, checked in code) -> mouth
     approvals: read-out allowlist, bound yes, tap, voice lock (local model)
     gate: each send checked against what you said
     reader: session notes, reports, briefings, conflicts, meeting notes
                              |
   one adapter per session: watch its record, send to it, hold its permission prompts
          |                        |                        |                     |
     Claude Code               OpenCode                   Codex          a session on another machine
  (PermissionRequest hook)                                                        |
                                              pinned TLS, HMAC-authenticated link |
                                                                                  |
                              node on another Mac or a Linux host (no audio, no keys):
                              the same adapters run there; it ships masked transcripts,
                              types your requests in, and re-checks each approval
```

The pipeline and the rules in detail: [docs/how-it-works.md](docs/how-it-works.md). The adapter contract and how to add a
harness: [docs/harnesses.md](docs/harnesses.md). Machines: [docs/multi-machine.md](docs/multi-machine.md).

## Limits

- **macOS only.** On Linux the daemon starts, but no real call has been made there. Windows is not supported.
- **The Mac app is built from source** too (`bin/pointe apps mac`, [how](docs/mac-app.md#getting-it)), signed for your
  own Mac and not notarized. Its
  call, typed words, its microphone's audio reaching Pointe, a request and a brain dump were run against a real daemon
  on one MacBook Pro; AirPods, device changes, the Touch ID sheet and a spoken sentence heard through it in this
  version were not.
- **The iPhone app is built from source** for now (`bin/pointe apps ios`, [how](docs/phone.md#getting-the-app)); it is
  not in the App Store, and not on TestFlight yet. With a free Apple Account a build opens for 7 days. It was tested on a real iPhone over Twingate, and in the simulator. Without it, the
  page works in a phone browser.
- **Synthetic evidence.** The benchmarks, the voice lock thresholds and the whisper numbers use synthetic voices. No
  bench on recorded people has been run, so use the voice lock at Approvals, and treat whisper recognition as limited.
- **Real hardware.** Drive mode has not been measured on car hands-free audio. Phone alerts depend on the app being alive
  (there is no push server). Conflict alarms have no live run with real OpenCode or Codex sessions.
- **Echo.** On laptop speakers, only Soniox ears have the echo guard; with other ears, use headphones. Known echo cases
  that are not solved are listed in [docs/how-it-works.md](docs/how-it-works.md#echo).
- **Vendor-hosted cloud sessions are out of reach.** Claude Code on the web and Codex Cloud have no public interface to
  read them or answer their approvals, so Pointe cannot join them. A cloud VM you run works, as a node. See
  [docs/cloud-sessions.md](docs/cloud-sessions.md).
- **Code running as you is trusted.** It can read Pointe's token and act as you. See [SECURITY.md](SECURITY.md#known-limits).

## Why Ballerine built this

Ballerine's engineers run several coding-agent sessions at once, and built Pointe for their own work. Ballerine is not
a developer-tools company and does not sell Pointe. It is shared because it is useful.

## Support

Pointe is community-supported, on a best-effort basis, with no SLA. Ask questions in
[Discussions → Q&A](https://github.com/ballerine-io/pointe/discussions/categories/q-a), propose features in
[Discussions → Ideas](https://github.com/ballerine-io/pointe/discussions/categories/ideas), and report bugs in
[GitHub issues](https://github.com/ballerine-io/pointe/issues). Report a vulnerability privately, never in an issue:
[GitHub private vulnerability reporting](https://github.com/ballerine-io/pointe/security/advisories/new) or
security@ballerine.com ([SECURITY.md](SECURITY.md)).

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md): your first pull request in 15 minutes, the offline tests (no keys, a few
minutes), the rules for changing behavior, and the DCO sign-off. What may come next, and how to vote on it:
[ROADMAP.md](ROADMAP.md). Report a vulnerability privately: [SECURITY.md](SECURITY.md). Please follow the
[Code of Conduct](CODE_OF_CONDUCT.md).
What changed in each version: [CHANGELOG.md](CHANGELOG.md); how a version is cut: [RELEASING.md](RELEASING.md).

Built on [Pipecat](https://github.com/pipecat-ai/pipecat). Third-party components and their licenses:
[THIRD_PARTY.md](THIRD_PARTY.md).

## License

MIT, © Ballerine. See [LICENSE](LICENSE).
