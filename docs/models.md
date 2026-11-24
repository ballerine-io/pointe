# Models and setups

Pointe runs its own models next to your coding agents. Each model has one job, called a **role**. A **setup** is a set of
vendors that fills every role. You choose a setup, add its keys, and can change any role by hand.

## The roles

| Role | Does | In plain words |
|---|---|---|
| **brain** | Understands what you said and decides what to do: answer, send to a session, switch, approve | The one you talk to |
| **reader** | Reads whole sessions: keeps notes on each one, turns each final message into a short report, writes briefings | The one who reads everything so you don't |
| **checker** | Checks each send against what you just said, before it reaches a session (also called the gate) | A second pair of eyes on every send |
| **ears** | Speech to text | Hears you |
| **mouth** | Text to speech | Speaks to you |

The brain does not speak on its own. Speech is a tool call that code checks before you hear it, and approvals follow
rules in code, not in the brain's prompt ([How it works](how-it-works.md)).

**The realtime front** is an experimental alternative to the brain, ears and mouth: one speech-to-speech model (Gemini
Live or OpenAI Realtime) that hears, decides and speaks. Set `CLAUDE_VOICE_FRONT=gemini` or `openai` in the daemon's
environment; the default is `brain`. With a realtime front, Pointe cannot bind your yes to a read-out it wrote itself,
so no request is approved by voice: every one waits for a tap. Meeting mode and challenge mode need the brain, and
"Voice stays on your Mac" refuses a realtime front (`pointe/daemon.py`, `vendors.resolve`). Gemini Live, measured as a whole
for hearing, is in [Benchmarks](benchmarks.md).

## The setups

There are six setups. Each one names the vendor for every role, what was measured, what a busy hour costs, and where
your words go. The table, with the file and row of every number: [Setups](setups.md). In short:

| Setup | Command | Keys |
|---|---|---|
| Free start | `pointe setup free` | Gemini |
| One OpenAI key | `pointe setup openai` | OpenAI |
| Two keys | `pointe setup two` | Soniox + Anthropic |
| Fastest and most accurate voice | `pointe setup full` | Anthropic + Soniox + ElevenLabs + Gemini |
| Voice stays on your Mac | `pointe setup voice-local` | Anthropic (Gemini optional) |
| Fully local | `pointe setup local` | none |

`pointe setup` lists them, with the one in use. `pointe setup <id>` switches; from then on Pointe uses exactly that
setup's vendors, whatever other keys the Keychain holds. Then `pointe restart`. The two local setups download their
models first (`pointe local voice`, `pointe local`).

On the page, Settings → Model keys does the same with buttons: **Use this setup** for a setup, **Add…** or **Replace…**
for a key, each key marked In use, Needed or Optional. The Mac app has the same.

How each default was chosen, and the per-role results: [Benchmarks](benchmarks.md).

## Keys

Pointe needs its own API keys, billed per use by each vendor. A Claude subscription (Pro or Max) runs Claude Code, but
it has no interface that other programs can use, so it is not a key Pointe can use. For Anthropic models, Pointe needs
an API key from console.anthropic.com. One Gemini key, or one OpenAI key, is enough to start.

```
pointe key gemini          # opens the vendor's key page and a Mac window for the key; checks it; restarts Pointe
pointe key check gemini    # one tiny live call with the saved key: works, refused, or unreachable
```

The vendors are `gemini`, `openai`, `anthropic`, `soniox` and `elevenlabs`. `--no-open` skips the vendor's page, and
`--no-restart` saves the key without restarting Pointe.

Pointe reads each key from its environment variable first, then from the macOS Keychain:

| Vendor | Environment variable | Keychain item |
|---|---|---|
| Gemini | `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) | `pointe.gemini-api-key` |
| OpenAI | `OPENAI_API_KEY` | `pointe.openai-api-key` |
| Anthropic | `ANTHROPIC_API_KEY` | `pointe.anthropic-api-key` |
| Soniox | `SONIOX_API_KEY` | `pointe.soniox-api-key` |
| ElevenLabs | `ELEVENLABS_API_KEY` | `pointe.elevenlabs-api-key` |

A key saved by a pre-release build of Pointe under its plain name (`gemini-api-key`) is still read. To save a key without the
window, type it into `security -i`, so it never reaches a command line or your shell history. At its `security>` prompt,
type this line with your macOS user name and your key (a `"` or `\` in the key needs a `\` before it), then `quit`:

```
add-generic-password -U -s pointe.gemini-api-key -a "<user name>" -w "<the key>"
```

Not `security add-generic-password ... -w` with `-w` last: its password prompt keeps only the first 128 characters, and
some keys are longer. `pointe key check gemini` tells whether the saved key works.

Keys reach only the daemon, and only when a role in use needs them. Never put a key in a file, in a command's
arguments, or in a chat with an agent. What leaves your Mac, by role: [SECURITY.md](../SECURITY.md#what-leaves-your-machine).

## Choosing models by hand

Each role can be set on its own, in `~/.claude-voice/config.json` or with an environment variable. The environment
wins. A role you do not set takes the first vendor in its order that has a key (`pointe/vendors.py`).

| Role | Setting | Environment | Value |
|---|---|---|---|
| brain | `"brain"` | `CLAUDE_VOICE_BRAIN` | `vendor:model`, such as `anthropic:claude-sonnet-5-5` |
| reader | `"reader"` | `CLAUDE_VOICE_READER` | `vendor:model` |
| checker | `"checker"` | `CLAUDE_VOICE_CHECKER` | `vendor:model`, such as `gemini:gemini-3.5-flash-lite` |
| ears | `"ears"` | `CLAUDE_VOICE_EARS` | a vendor: `soniox`, `gemini`, `openai`, `elevenlabs` or `local` |
| mouth | `"mouth"` | `CLAUDE_VOICE_MOUTH` | `vendor:model[:voice]`, such as `elevenlabs:eleven_v4_turbo` |

For example:

```json
{
  "brain": "anthropic:claude-sonnet-5-5",
  "reader": "gemini:gemini-3.8-flash",
  "checker": "gemini:gemini-3.5-flash-lite",
  "ears": "soniox",
  "mouth": "elevenlabs:eleven_v4_turbo"
}
```

Restart after a change (`pointe restart`). `pointe doctor` shows what runs in each role. `pointe setup <id>` writes the
roles of the setup you choose, so it replaces roles you set by hand.

Only Soniox ears have the echo guard, which lets you use laptop speakers. With any other ears, use headphones.

## Azure OpenAI and other OpenAI-compatible hosts

`openai_url` in `config.json` (or `CLAUDE_VOICE_OPENAI_URL`) points the OpenAI text models (brain, reader, checker) at
another host, such as your Azure OpenAI resource. The OpenAI key then belongs to that host, so OpenAI's own ears, mouth
and realtime front are refused. The address must start with `https://`. Not measured. Setup and details:
[OpenAI models from another host](features/openai-url.md).

## Local models

Two setups run models on your Mac:

- **Voice stays on your Mac** (`pointe local voice`): Whisper hears and Kokoro speaks on the Mac, so no audio reaches a
  vendor. The brain, reader and checker stay in the cloud and get text. About 2 GB of models; any Apple-silicon Mac.
  [Voice stays on your Mac](features/voice-stays-local.md).
- **Fully local** (`pointe local`): the ears, the mouth, and one text model (Gemma 4 26B A4B) for the brain, reader and
  checker. No key is read and nothing leaves the Mac. Needs an Apple-silicon Mac with 32 GB of memory and about 19 GB
  of disk; slower and less accurate, by measure. [Fully local](features/local.md).

`pointe local status` shows what is on disk and whether the model answers; `pointe local off` goes back to your
vendors. Any OpenAI-compatible server can serve the text roles instead: set them to `local:<model>` and `local_url` (or
`CLAUDE_VOICE_LOCAL_URL`) to its address, such as Ollama's `http://localhost:11434/v1`. Not measured
([Other machines and servers](features/local.md#other-machines-and-servers)).
