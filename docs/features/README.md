# Features

How each feature behaves now. Every feature works on the page and in the iPhone app, with the same names and copy; the
daemon holds the state and enforces the rules, so the two clients never disagree.

Two rules hold for all of them: a mode or feature can only narrow what a spoken word may do, never widen it; and a no
from any voice denies a pending request, in every mode.

| Feature | In one line |
|---|---|
| [Voice lock](voice-lock.md) | Only your voice counts, for approvals or for everything; checked on this Mac |
| [Self-learning vocabulary](vocabulary.md) | Fix a misheard name once, and the next call hears it right |
| [Drive & walk mode](drive-mode.md) | Short answers, nothing to look at, and only safe requests approved by voice |
| [Push to talk](push-to-talk.md) | Nothing leaves the Mac unless you hold the key or the button |
| [Audio briefings](briefings.md) | "Brief me on the night": what each session did, failed and waits on |
| [Brain dump](brain-dump.md) | Dump your thoughts; Pointe structures them into a prompt in your words, and sends it only when you say |
| [Challenge me](challenge.md) | The voice argues against your plan, grounded in your sessions, and cannot send |
| [Wrist approvals and desktop alerts](alerts.md) | A session needs you: the watch taps, the desktop notifies |
| [Show while it says](show-while-it-says.md) | The file, diff or failing test appears on screen as the voice mentions it |
| [Whisper mode](whisper-mode.md) | Quiet replies, a raised microphone, the same approval rules |
| [Conflict alarm](conflict-alarm.md) | Two sessions claim opposite things about the same work: you hear it at once |
| [Meeting mode](meeting-mode.md) | Notes, lookups and a raised hand in a meeting, with consent and no sends |
| [Start a new session](new-session.md) | "Start a Codex session in shop": read back, started on your yes, only in folders you already work in |
| [Night shift](night-shift.md) | "Tonight: billing fixes the retry tests": the sessions work while you sleep, nothing is approved for you, and the morning briefing leads with it |
| [Voice stays on your Mac](voice-stays-local.md) | Ears and mouth on your Mac, no audio to any vendor; the cloud brain gets text only |
| [Fully local](local.md) | Every model on your Mac, no keys, nothing sent out; slower and less accurate, by measure |

The core, which these build on:

- [How it works](../how-it-works.md): the pipeline, the rules enforced in code, echo handling.
- [Harnesses](../harnesses.md): Claude Code, OpenCode and Codex, and how to add another.
- [Phone access](../phone.md): the iPhone app, pairing, alerts and the Apple Watch.
- [Security](../../SECURITY.md): the threat model and what each route and key can do.

The original plan these were built from, with its reasoning and the alternatives it weighed, is in
[docs/design/2026-11-feature-plan.md](../design/2026-11-feature-plan.md). Where the two differ, these pages describe the
behavior.
