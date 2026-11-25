# Changelog

One entry per version, newest first. Each line is the subject of that version's commit; the commits before it, back to
the previous version, hold the detail. Versions are tagged (`git log v0.8.0..v0.8.1`). The version is the one in
`.claude-plugin/plugin.json`, which the page, the site and the apps show. How a version is cut:
[docs/releasing.md](docs/releasing.md).

Pointe is in beta while its major version is 0: it works, it is used every day, and it is still changing. Report what
breaks in [GitHub issues](https://github.com/ballerine-io/pointe/issues).

## 0.8 (beta)

- **Unreleased** (beta): New Claude Code sessions Pointe starts skip permission prompts by default, with a setting to ask
  before actions and "start a session that asks first" for one session

  The owner's decision, 2026-11-25, for everyone and for the public release (SECURITY.md, "Starting a session"). The
  risk, once: such a session can edit files and run commands without asking, so there are no requests to approve.
  Settings → Permissions for new sessions on the page, the iPhone and the Mac; "new sessions ask first" by voice. Pointe
  says the risk the first time, and asks for Claude Code's one-time consent out loud instead of leaving it in a
  terminal. Joined and reopened sessions, night shifts, Codex and OpenCode are not changed.
- **0.9.0** (2026-11-26, beta): Pointe runs as a hub on Linux (keys in the login keyring, sessions in tmux, pairing by QR in the terminal); new Claude Code sessions Pointe starts skip permission prompts by default, with a setting to ask first; a request aimed at a session by what it works on goes there, "Pointe." answers "which session?", and "Approved." over Pointe's own question answers it
- **0.8.7** (2026-11-25, beta): The iPhone app is ready for App Store review (a privacy policy link, privacy manifests, no "beta" on the iPhone, the Sessions title whole), AirPods turn the mic off and on during a call on the Mac, an overview reaches a session signed in by a key, and a request's reminder and read-out are said as a person says them
- **0.8.6** (2026-11-25, beta): "Only when I say Pointe" acts only on words that name Pointe or a session, an optional short tone before a background session's report, "What's going on everywhere?" is answered by the sessions themselves, and replies sound spoken: no greeting that ends in a question, a session by its plain name, a caveat in a few words
- **0.8.5** (2026-11-25, beta): The wait says "Thinking…", Pointe waits 1.3 s before it answers, a command that is long to hear goes back for plain ones and a request is read once, "stop" and "never mind" keep a request from being sent, a question is not an answer to a request, and "yes" while Pointe talks does not cut it off
- **0.8.4** (2026-11-25, beta): Approvals and interruptions hold up by voice: every request can be approved after it is read in full, a command that only looks is read in a few words, a yes and a no always land with "Approved." or "Denied.", no turn ends in silence, a request you talked over is not sent, and "mm-hm" no longer ends an answer
- **0.8.3** (2026-11-24, beta): Mute and skip sit beside the status line: one mute button replaces reading mode, skip moves on to the next message, a switch stops speech at once, and the conversation's text can be copied

  What is in it:
  - One mute button beside the status line replaces reading mode. Muted, Pointe writes its replies and the status
    says "Writing…"; muting in the middle of a reply stops the audio at once. "Stop talking, I'll read" and "talk
    again" still work.
  - Skip what Pointe is saying and go on to the next message: a button beside the mute button, ⌃⌥S from any app on
    the Mac, or "skip" or "next" by voice.
  - A switch stops speech at once: moving to the orchestrator or to a session, by a click or by voice, cuts what
    Pointe is saying and clears what waited to be said.
  - The conversation's text can be selected and copied.
  - "Mute" now means only Pointe's voice. The microphone is on or off: the state reads "Mic off".
  - Mac app: the two bubble switches in Settings always take a click, the bubble's dot for a waiting session no
    longer sits over the mic's state, and the setup guide no longer says the first start downloads 180 MB.
- **0.8.2** (2026-11-24, beta): pointe key saves a key longer than 128 characters whole, and says so only after reading it back
- **0.8.1** (2026-11-24, beta): Pointe for Mac is one signed, notarized download: drag Pointe from Pointe.dmg to Applications and open it, and the app installs Pointe (checked, no Terminal), asks one question, takes your key and starts your first call; Uninstall Pointe… is in its menu
- **0.8.0** (2026-11-24, beta): The first public release. Beta: work in progress.

  What is in it:
  - One voice over every Claude Code, OpenCode and Codex session you join. Ask what each one did, switch by saying its
    name, send requests, say "stop", and answer permission prompts out loud, under rules enforced in code: a spoken yes
    approves only a request Pointe read out itself.
  - Install as a Claude Code plugin, or without Claude Code for Codex and OpenCode (`install.sh`, checked against the
    release's SHA-256). Setup takes one command and one key, with your vendor keys in the macOS Keychain. Or run
    `pointe local`: every model on your Mac.
  - Sessions by voice: add the ones already open, reopen recent ones, start new ones, close them.
  - Meeting mode, reading mode (no speech, every reply as text), brain dump, audio briefings, challenge me, drive mode,
    whisper mode, push to talk, the voice lock, the conflict alarm and the night shift.
  - Several machines under one voice. The iPhone app (Lock Screen, Control Center, the Action button, a widget) and the
    Mac app, built from source for now. Calls hold up on a weak network, and a phone that cannot reach your Mac says why.
  - A published security review ([docs/security/reviews/](docs/security/reviews/)) and the Pointe Conversational
    Engineering Benchmarks, with every result and its limits in [docs/benchmarks/](docs/benchmarks/README.md).

  Thanks to Omer Harell for OpenAI models from another host (`openai_url`).
