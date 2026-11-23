# Features

How each feature behaves now. The daemon holds the state and enforces the rules, so the page, the iPhone app and the
Mac app never disagree. Most features work in all four ways in: by voice, on the page, in the iPhone app and in the Mac
app. The second table says where one does not, and each page says why.

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
| [Add sessions](add-sessions.md) | "Connect to the session about the pentest", "reopen yesterday's session about billing": found, read back, joined on your yes; no typing in the session |
| [Night shift](night-shift.md) | "Tonight: billing fixes the retry tests": the sessions work while you sleep, nothing is approved for you, and the morning briefing leads with it |
| [Clean up my words](clean-up-my-words.md) | Under each thing you say, a clean version of what the voice understood |
| [Voice stays on your Mac](voice-stays-local.md) | Ears and mouth on your Mac, no audio to any vendor; the cloud brain gets text only |
| [Fully local](local.md) | Every model on your Mac, no keys, nothing sent out; slower and less accurate, by measure |
| [OpenAI models from another host](openai-url.md) | Azure OpenAI or another OpenAI-compatible host for the text models, with the key in the Keychain; not measured |

Where each one works, and how to reach it:

| Feature | Voice | Page | iPhone | Mac |
|---|---|---|---|---|
| [Voice lock](voice-lock.md#use-it) | no phrase; enrolment listens to you read lines on the call | Settings → Voice lock | Settings → Voice lock | Settings → Voice lock |
| [Self-learning vocabulary](vocabulary.md#use-it) | no: a fix is typed | click a line you said; Settings → Dictionary | tap a line you said; Settings → Dictionary | click a line you said; Settings → Dictionary |
| [Drive & walk mode](drive-mode.md#use-it) | "drive mode", "I've stopped" | no Drive button (for a phone in a car); shows it, "I've stopped" | Drive (the car) at the top | no Drive button, as on the page; shows it, "I've stopped" |
| [Push to talk](push-to-talk.md#use-it) | no: a setting | the switch above the mic; Space | the switch above the mic; the Action button | the switch above the mic; the talk shortcut |
| [Audio briefings](briefings.md#use-it) | "brief me on the night" | Briefing in the dock | Settings → Briefing | Settings → Briefing; Call → Briefing |
| [Brain dump](brain-dump.md#use-it) | "brain dump", then "done" | Brain dump in the dock | Brain dump in the bottom bar | Brain dump in the bottom bar; Call → Brain Dump |
| [Challenge me](challenge.md#use-it) | "challenge me", then "verdict" | Challenge in the dock | Settings → Challenge | Settings → Challenge |
| [Wrist approvals and desktop alerts](alerts.md#use-it) | no: a setting | Settings → Alerts | Settings → Alerts | Settings → Alerts |
| [Show while it says](show-while-it-says.md#use-it) | nothing to say: it follows the voice | the Showing pane, always on | the Showing card, after Settings → Show while it says | the Showing card, always on |
| [Whisper mode](whisper-mode.md#use-it) | "whisper mode", "back to normal" | Whisper in the dock | Settings → Whisper | Settings → Whisper |
| [Conflict alarm](conflict-alarm.md#use-it) | the alarm is spoken; "I know" dismisses it | the card; Settings → Conflict alarm | the card; Settings → Conflict alarm | the card; Settings → Conflict alarm |
| [Meeting mode](meeting-mode.md#start) | "meeting mode, listening", once consent was given | Meeting in the dock | Start a meeting at the top | Start a meeting at the top; Call → Start a Meeting |
| [Start a new session](new-session.md#use-it) | "start a new Codex session in shop" | New session under the sessions | Sessions → New session | New session under the sessions; File → New Session |
| [Add sessions](add-sessions.md#use-it) | "connect to the session about the pentest" | Add sessions under the sessions | Sessions → Add sessions | Add sessions under the sessions; File → Add Sessions |
| [Night shift](night-shift.md#use-it) | "tonight: billing fixes the retry tests" | Night shift under the sessions | Settings → Night shift | Settings → Night shift; Call → Night Shift |
| [Clean up my words](clean-up-my-words.md#use-it) | no: a switch | Clean up my words at the top | Settings → Clean up my words | Settings → Clean up my words |
| [Voice stays on your Mac](voice-stays-local.md#use-it) | no | Settings → Model keys → Use this setup, on the Mac | no: chosen on the Mac; Settings shows it | Settings → Model keys → Setup |
| [Fully local](local.md#use-it) | no | Settings → Model keys → Use this setup, on the Mac | no: chosen on the Mac; Settings shows it | Settings → Model keys → Setup |
| [OpenAI models from another host](openai-url.md#turn-it-on) | no | no: set in `config.json` | no | no |

Settings in the apps is the ••• button at the top (on the Mac also ⌘,). Call and File are menus in the Mac's menu bar.
On a narrow page, the sessions and Settings are behind the Sessions button.

## Core

Always on, and described elsewhere:

- **Several sessions, one voice.** Say a session's name to talk to it, ask "by the way" questions, choose Orchestrator or
  Session: [What it does](../../README.md#what-it-does), and the targeting rule in
  [How it works](../how-it-works.md#rules-enforced-in-code).
- **Approvals.** A spoken yes approves only right after the daemon's own read-out; a tap always works:
  [Approvals, exactly](../how-it-works.md#approvals-exactly).
- **The live transcript, typing and correcting.** The conversation as it happens, Type instead of talking, and a fix to
  what was heard: [What it does](../../README.md#what-it-does); what a fix teaches is in
  [Self-learning vocabulary](vocabulary.md).
- **Turn taking.** "Don't interrupt me" holds the voice until "go ahead"; Settings → Wait before answering sets how long a
  pause ends your sentence: [design/turn-taking.md](../design/turn-taking.md).
- **Machines.** Sessions on your other Macs and Linux machines on the same voice: [Machines](../multi-machine.md).
- **Harnesses.** Claude Code, OpenCode and Codex, and how to add another: [Harnesses](../harnesses.md).

The rest of the core, which these build on:

- [How it works](../how-it-works.md): the pipeline, the rules enforced in code, echo handling.
- [Connect your phone](../phone.md): routes and pairing; [The iPhone app](../iphone-app.md): building it, alerts and the Apple Watch.
- [The Mac app](../mac-app.md): the menu bar item, the window, the menus and their keys.
- [Security](../../SECURITY.md): the threat model and what each route and key can do.

The original plan these were built from, with its reasoning and the alternatives it weighed, is in
[docs/design/2026-11-feature-plan.md](../design/2026-11-feature-plan.md). Where the two differ, these pages describe the
behavior.
