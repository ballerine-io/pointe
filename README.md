# Pointe

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

@@DEMO@@

- **Hands-free across sessions.** One conversation over every session you joined, with a live transcript on the page and
  in the iPhone app.
- **Strict approvals.** A spoken yes approves only a request the daemon read out itself from what will run, and only
  right after it. Anything it cannot read out waits for a tap. A no from any voice denies.
- **Any harness.** [Claude Code](https://code.claude.com), [OpenCode](https://opencode.ai) (v2) and
  [Codex CLI](https://github.com/openai/codex) (started as `codex --remote unix://`), side by side in one call.
- **Your keys, or none.** You pay the vendors directly. Or run `pointe local`: every model on your Mac, no key, nothing
  sent out, with its measured cost in speed and accuracy. [docs/features/local.md](docs/features/local.md).

## Install

You need macOS, [Claude Code](https://code.claude.com) 2.1.224 or newer, Chrome, headphones, and one model key, or an
Apple-silicon Mac with 32 GB of memory for the fully local mode.

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

| Command | Does |
|---|---|
| `/pointe:setup` | guided setup: keys, first call, phone |
| `/pointe:voice` | join this session to the voice (starts the daemon if needed) |
| `/pointe:open` | open the page again |
| `/pointe:leave` | take this session off the voice (or say "disconnect billing", or use × on the page) |
| `/pointe:stop` | stop all voice |
| `/pointe:doctor` | what runs here, what is missing, and the one key that would help most |
| `pointe local` | fully local: download and start the local models, no keys ([details](docs/features/local.md)) |
| `/pointe:voice-review` | ask a session what happened in the last call |

OpenCode and Codex sessions join with `pointe join opencode` or `pointe join codex`: see
[docs/harnesses.md](docs/harnesses.md).

## What it does

**The core**

- **One voice over many sessions.** Say a session's name to talk to it or switch to it. Background sessions stay quiet
  except for "finished" or "needs approval". Ask "by the way" questions: they are answered from a read-only copy, so the
  live session is never interrupted.
- **Session notes.** A reading model keeps each session's goal, state, decisions, what was ruled out and what is open,
  and turns each final message into what you need to hear. [How it works](docs/how-it-works.md).
- **Live transcript.** The page shows the conversation as it happens, the exact text of every pending request with
  Approve and Deny, and lets you type or correct what was heard.
- **iPhone app.** The same call and controls on your phone, paired once by QR code over Tailscale, a VPN such as
  Twingate, or Wi-Fi. Approve needs Face ID. [docs/phone.md](docs/phone.md).
- **Several harnesses and accounts** in one call, each session with its own approvals. [docs/harnesses.md](docs/harnesses.md).

**Features** (each page says how to use it, the rules, what was measured, and the limits)

| | |
|---|---|
| [Voice lock](docs/features/voice-lock.md) | Only your voice counts, for approvals or for everything. Checked on this Mac. |
| [Self-learning vocabulary](docs/features/vocabulary.md) | Fix a misheard name once, and the next call hears it right. |
| [Drive & walk mode](docs/features/drive-mode.md) | Short answers, nothing to look at, and only requests that lose nothing approved by voice. |
| [Push to talk](docs/features/push-to-talk.md) | No audio leaves the Mac unless you hold the key or the button. |
| [Audio briefings](docs/features/briefings.md) | "Brief me on the night": what each session did, failed and waits on. |
| [Challenge me](docs/features/challenge.md) | The voice argues against your plan, grounded in your sessions, and cannot send. |
| [Wrist approvals and desktop alerts](docs/features/alerts.md) | A session needs you: the watch taps, the desktop notifies. |
| [Show while it says](docs/features/show-while-it-says.md) | The file, diff or failing test appears on screen as the voice mentions it. |
| [Whisper mode](docs/features/whisper-mode.md) | Quiet replies and a raised microphone, with the same approval rules. |
| [Conflict alarm](docs/features/conflict-alarm.md) | Two sessions claim opposite things about the same work: you hear it at once. |
| [Meeting mode](docs/features/meeting-mode.md) | Notes, lookups and a raised hand in a meeting, with consent and no sends. |
| [Fully local](docs/features/local.md) | Every model on your Mac, no keys, nothing sent out; slower and less accurate, by measure. |

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

Pointe has no server and no telemetry, and the page loads nothing from outside your Mac. What leaves the Mac goes to the
vendors you chose, under your keys:

| What | Goes to |
|---|---|
| Your speech, plus hints: your dictionary, session and folder names, names from session notes | the ears vendor (Soniox, Google Gemini, OpenAI or ElevenLabs) |
| Session content: transcripts, notes, reports, briefings, conflict checks | the brain and reader vendors (Anthropic, Google Gemini or OpenAI) |
| What the bot says, which can quote session content | the mouth vendor (ElevenLabs, Google Gemini, Soniox or OpenAI) |
| What you said, each session's latest lines, goal, folder path and up to 40 file names | the gate vendor |
| In a meeting you started: the room's audio, and transcript windows | Soniox, and the reader vendor |

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

| Role | Does | Best measured |
|---|---|---|
| `ears` | speech to text | `soniox` |
| `brain` | decides what to say and do | `anthropic:claude-sonnet-5-5` |
| `reader` | reads whole sessions and reports | `anthropic:claude-sonnet-5-5` |
| `checker` | checks each send against what you asked | `gemini:gemini-3.5-flash-lite` |
| `mouth` | text to speech | `elevenlabs:eleven_v4_turbo` |

| Keys | Full audio test (real sessions, synthetic speech) | A busy hour |
|---|---|---|
| Anthropic, Soniox, ElevenLabs, Gemini | 34 of 35; echo 4 of 4 | about $1 |
| Anthropic, Soniox | 30 of 35 (31 with the two-session suite rerun); echo 3 of 4 | about $1.20 |
| Gemini only (no echo guard: use headphones; replies take about 4 s) | 28 of 35; echo 0 of 4 | about $0.40, plus Gemini ears |
| OpenAI only (no echo guard: use headphones; weak on Hebrew) | 24 of 35; echo 0 of 4 | about $0.60, plus OpenAI ears |

The audio test is the three suites in `tests/e2e/run_all.sh` with only those keys visible, one run each on 2026-11-13. `bin/voice-doctor` tells you which row you are on.
The hourly cost is arithmetic from measured and list prices, not a metered bill.

**Fully local:** `pointe local` downloads and starts Whisper (ears), Kokoro (mouth) and Gemma 4 26B A4B (brain,
reader and gate) on this Mac, and reads no key. On an M5 Pro with 64 GB, the brain passed 76.9% of 78 cases (Sonnet
91.9%) and decided in 3.4 s at the median (Sonnet 1.8 s), the ears got 85.7% of intents (Soniox 95.4%), and 10 of 19
single-session audio checks passed, every approval check among them. It has no Hebrew voice. It needs 32 GB of memory
and about 19 GB of disk. [docs/features/local.md](docs/features/local.md).

On macOS, keep keys in the Keychain: `pointe key <vendor>` opens a window for it.

## Benchmarks

The defaults come from benchmarks in `bench/`, all on synthetic data; re-run them with your own keys. Summary from
[docs/benchmarks.md](docs/benchmarks.md):

- **Ears:** 560 clips (English, Hebrew, mixed, short yes/no; 4 voices; clean and noisy). Soniox stt-rt-v5 got intent
  right 95.4% of the time, word error 0.062, latency p50 0.36 s.
  [`bench/results/report.txt`](bench/results/report.txt)
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
- **Which setups were tested end to end:** [`bench/results/combinations.md`](bench/results/combinations.md)

Not measured for any setup: a real human voice on a real call.

## Architecture

```
 Chrome page (loopback)          iPhone app (paired TLS, pinned)
          \                               /
           one WebSocket per call: audio both ways, plus status and taps
                              |
   daemon on your Mac (Python, Pipecat)
     ears -> echo guard -> brain (tools; speech is a tool call, checked in code) -> mouth
     approvals: read-out allowlist, bound yes, tap, voice lock (local model)
     gate: each send checked against what you said
     reader: session notes, reports, briefings, conflicts, meeting notes
                              |
   one adapter per session: watch its record, send to it, hold its permission prompts
          |                        |                        |
     Claude Code               OpenCode                   Codex
  (PermissionRequest hook)
```

The pipeline and the rules in detail: [docs/how-it-works.md](docs/how-it-works.md). The adapter contract and how to add a
harness: [docs/harnesses.md](docs/harnesses.md).

## Limits

- **macOS only.** On Linux the daemon starts, but no real call has been made there. Windows is not supported.
- **The iPhone app is built from source** in Xcode for now; it is not in the App Store. It was tested on a real iPhone
  over Twingate, and in the simulator. Without it, the page works in a phone browser.
- **Synthetic evidence.** The benchmarks, the voice lock thresholds and the whisper numbers use synthetic voices. No
  bench on recorded people has been run, so use the voice lock at Approvals, and treat whisper recognition as limited.
- **Real hardware.** Drive mode has not been measured on car hands-free audio. Phone alerts depend on the app being alive
  (there is no push server). Conflict alarms have no live run with real OpenCode or Codex sessions.
- **Echo.** On laptop speakers, only Soniox ears have the echo guard; with other ears, use headphones. Known echo cases
  that are not solved are listed in [docs/how-it-works.md](docs/how-it-works.md#echo).
- **Code running as you is trusted.** It can read Pointe's token and act as you. See [SECURITY.md](SECURITY.md#known-limits).

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md): the offline tests (no keys, under a minute), the rules for changing behavior, and
the DCO sign-off. Report a vulnerability privately: [SECURITY.md](SECURITY.md). Please follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

Built on [Pipecat](https://github.com/pipecat-ai/pipecat). Third-party components and their licenses:
[THIRD_PARTY.md](THIRD_PARTY.md).

## License

MIT, © Ballerine. See [LICENSE](LICENSE).
