# Compared to other tools

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
  waits for a tap ([SECURITY.md](../SECURITY.md#what-a-spoken-word-can-do)). In Happy's Android source the voice model allows or denies through a
  tool call, under a prompt rule to wait for the user
  ([`VoiceTools.kt`](https://github.com/slopus/happy/blob/main/packages/happy-android/app/src/main/kotlin/com/slopus/happy/voice/VoiceTools.kt),
  [`VoicePrompts.kt`](https://github.com/slopus/happy/blob/main/packages/happy-android/app/src/main/kotlin/com/slopus/happy/voice/VoicePrompts.kt));
  we did not read its other clients.
- **No relay and no account.** The call is between your browser or phone and a daemon on your Mac. Happy's relay
  carries encrypted messages between your devices, and its voice sends audio, the session list, recent messages and
  permission requests to ElevenLabs.
- **You choose each model, or run them on the Mac.** Three or four vendors for each role, two local modes, and no metered voice minutes.
- **It joins sessions that are already running**, with `/pointe:voice` or by voice from outside ("connect to the session about the pentest"), and they keep their context. It can also start a new one, or reopen a closed one, on your yes.

**The built-in voices** need nothing installed and work on Linux and Windows too. Claude Code's `/voice` is for
dictating a prompt and needs a Claude.ai sign-in. Codex voice is a full spoken conversation over Codex tasks; in the
desktop app it needs a paid ChatGPT plan. Pointe is one conversation over Claude Code, OpenCode and Codex sessions together, on your own
keys. Dictation and Pointe work side by side.

**The phone remotes** (Remote Control, Moshi, Paseo, Happy) reach your sessions from anywhere with store apps. Pointe's
iPhone app is built from source for now and reaches the Mac only over a network you set up.
