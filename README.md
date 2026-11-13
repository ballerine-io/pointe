# Pointe

Talk to all your Claude Code sessions. Ask what each one did, switch by saying its name, and answer its permission prompts out
loud, from across the room.

Dictation types for you. Pointe holds a conversation: one voice that knows every session you joined to it, while the sessions do
the work and keep their context. It runs on your machine, with no server and no account. You bring the model keys, or run local models.

```
You:     What is the payments session doing?
Pointe:  It finished the retry fix. Tests pass. It wants to know if it should open the PR.
You:     Yes. And tell the docs session to update the changelog.
Pointe:  Docs is on it.
You:     By the way, why did payments drop the queue idea?
Pointe:  Duplicate charges during failover. It decided that an hour ago.
```

@@DEMO@@

Works with [Claude Code](https://code.claude.com), [OpenCode](https://opencode.ai) (v2) and [Codex CLI](https://github.com/openai/codex) (started as `codex --remote unix://`); Pi is next.
How harnesses plug in: [docs/harnesses.md](docs/harnesses.md).

## Try it in 5 minutes

**Not a developer, or using the Claude desktop app?** One command installs the plugin, and `/pointe:setup` does the rest,
keys included: [docs/install.md](docs/install.md).

You need [Claude Code](https://code.claude.com) 2.1.224 or newer, [uv](https://docs.astral.sh/uv/), Chrome, headphones and one key.

```
export GOOGLE_API_KEY=...        # or OPENAI_API_KEY, in the shell you start Claude Code from
claude plugin marketplace add https://github.com/ballerine-io/pointe.git
claude plugin install pointe@pointe
claude
```

Then, in any session:

```
/pointe:voice
```

The first run downloads about 180 MB. A tab opens: allow the mic, press Connect, and talk. Run `/pointe:voice` in each session you
want to reach.

| | |
|---|---|
| `/pointe:setup` | guided setup: keys, first call, phone |
| `/pointe:open` | open the page again |
| `/pointe:leave` | take this session off the voice (or say "disconnect billing", or use × on the page) |
| `/pointe:stop` | stop all voice |
| `/pointe:doctor` | what runs here, and what is missing |
| `/pointe:voice-review` | ask a session what happened in the last call |

Tested on macOS with Chrome. On Linux the daemon starts, but no real call has been made there. Windows is not supported yet.

## Is it safe to let a voice approve things?

- **You decide.** Set `"approvals": "terminal"` in `~/.claude-voice/config.json`, and prompts stay in the terminal as they always were.
- **Otherwise:** simple commands are read out (`git push --force origin main`, `rm -rf build`) and a plain yes right after
  approves them. Anything more complex shows on the page, word for word, with Approve and Deny. Silence, "okay, tell me
  more", and a yes to any other question approve nothing. Your Claude Code deny rules still apply.
- **Voice is not authentication.** Anyone your mic can hear can answer. Do not use voice approvals in a room you do not trust.
- **Prompt injection:** what a session reports is data, not instructions. A model gate checks each send against what you just said and
  refuses when it cannot check. It lowers the risk and does not remove it.
- **Only sessions you join.** The plugin adds a `PermissionRequest` hook to every session, and it does nothing unless that session ran
  `/pointe:voice` and a call is live. Hang up, and the normal terminal dialog opens.

The whole threat model, including what we do not defend against: [SECURITY.md](SECURITY.md).

## Choose your models

Each role is separate. Set any of them in `~/.claude-voice/config.json`, or with `CLAUDE_VOICE_<ROLE>` (the environment wins):

```json
{ "brain": "anthropic:claude-opus-5-5", "reader": "openai:gpt-6-sol", "mouth": "gemini:gemini-3.8-flash-lite-tts" }
```

| Role | Does | Best measured |
|---|---|---|
| `ears` | speech to text | `soniox` |
| `brain` | decides what to say and do | `anthropic:claude-sonnet-5-5` |
| `reader` | reads whole sessions and reports | `anthropic:claude-sonnet-5-5` |
| `checker` | checks each send against what you asked | `gemini:gemini-3.5-flash-lite` |
| `mouth` | text to speech | `elevenlabs:eleven_v4_turbo` |

Vendors: `anthropic`, `gemini`, `openai`, `soniox`, `elevenlabs`, `local`. A role you do not set takes the first vendor with a key.

| Keys | What you get | Full audio test (real sessions, synthetic speech) | A busy hour |
|---|---|---|---|
| Anthropic, Soniox, ElevenLabs, Gemini | Best measured | 33 of 35; echo 4 of 4 | about $1 |
| Anthropic, Soniox | Best with two keys | 30 of 35; echo 2 of 4, 3 of 4 on a rerun | about $1.20 |
| Gemini only | Simplest start. No echo guard: use headphones. Replies take about 4 s, and a Hebrew yes is heard as "Ken" | 27 of 35; echo 3 of 4 | about $0.40, plus Gemini ears |
| OpenAI only | No echo guard: use headphones. Weak on Hebrew | 29 of 35; echo 1 of 4 | about $0.60, plus OpenAI ears |

The audio test is the three suites in `tests/e2e/run_all.sh`, with only those keys visible: one session, two sessions, and the bot's own voice
leaking into the mic, one run each on 2026-11-08. `bin/voice-doctor` tells you which row you are on, and the one key that would help most.

**Run without any cloud:** set every role to `local` (`"ears": "local", "mouth": "local", "brain": "local:<model>"`, the same
for `reader` and `checker`). Ears are Whisper, the mouth is Kokoro, and text models come from any OpenAI-compatible server
(Ollama by default, `CLAUDE_VOICE_LOCAL_URL` for others). It is not a conversation yet: the best local brains
measured a median reply of 13 to 27 seconds, against 1.8 for Sonnet. Local ears and mouth have not been benchmarked.

On macOS, keep keys in the Keychain instead of the environment: `/pointe:setup`, or `bin/pointe key <vendor>`, opens a
window that saves each one there. By hand, the command prompts, so the key stays out of your history:
`security add-generic-password -U -s anthropic-api-key -a "$USER" -w`. The other names are `soniox-api-key`, `elevenlabs-api-key`,
`gemini-api-key` and `openai-api-key`.

**Cost:** you pay the vendors directly. A busy hour on the best setup is about $1, by arithmetic from measured and list prices, not
from metered calls: 60 replies of 30 words, 10 reports, and up to two Soniox streams. Details in [docs/benchmarks.md](docs/benchmarks.md).

**What leaves your machine:** your speech goes to the ears vendor, and session content to the brain, reader, checker and mouth vendors.
Choose vendors you are allowed to send that to.

## More

- [How it works](docs/how-it-works.md): the pipeline, the session notes, reading a call's log, the tests
- [Benchmarks](docs/benchmarks.md): how the defaults were chosen, and how little of that is a real human voice so far
- [Phone access](docs/phone.md): the iPhone app (pair once by QR code over Twingate, Tailscale or Wi-Fi; tested on a real iPhone over Twingate only), or the page in a phone browser
- [Starting a session with a channel](docs/how-it-works.md#channel-mode): you do not need it for voice approvals

## Status

Young, built largely with Claude Code, and used daily by its author. Expect rough edges and tell us where it breaks.
Built on [Pipecat](https://github.com/pipecat-ai/pipecat). MIT: [LICENSE](LICENSE). [CONTRIBUTING.md](CONTRIBUTING.md) says how to change it safely.
