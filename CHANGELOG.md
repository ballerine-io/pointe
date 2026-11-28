# Changelog

One entry per version, newest first. Each line is the subject of that version's commit; the commits before it, back to
the previous version, hold the detail. Versions are tagged (`git log v0.8.0..v0.8.1`). The version is the one in
`.claude-plugin/plugin.json`, which the page, the site and the apps show. How a version is cut:
[docs/releasing.md](docs/releasing.md).

Pointe is in beta while its major version is 0: it works, it is used every day, and it is still changing. Report what
breaks in [GitHub issues](https://github.com/ballerine-io/pointe/issues).

## 0.10 (beta)

- **0.10.2** (2026-11-27, beta): People approve and start sessions on machines they were invited to, agents join the voice behind a flag, quick settings for reply length and speed, and no lost reports from other machines
- **0.10.1** (2026-11-26, beta): Speech no longer breaks between words on the iPhone, the page and the Mac, and the iPhone app gets the People and Machines screens
- **0.10.0** (2026-11-26, beta): Machines running different Pointe versions say which one to update and how, a correction takes a request back from the wrong session, mute holds through quick taps, and Linux hubs, the iPhone and the Mac get their fixes

  What is in it:
  - Several people can use one machine, each from their own voice, and your voice can hold a machine somebody invited you to

    The owner of a machine invites a person by name (`pointe people invite dana`, or Invite a person on the page, the
    iPhone and the Mac). The person adds the machine to their own Pointe with the one-time line (`pointe machine add`, or
    Add a machine: paste it, or scan it on the iPhone) and talks to its sessions from their own call, with their own
    keys. Each session shows whose it is, the agent reads who sent each request, and the machine's journal records it. A
    person can be invited to watch only, the owner keeps a session to themselves with Private, and removing one person
    touches nobody else. A session that works on somebody else's request refuses yours until you say "send it anyway".
    You hear the reports of the turns you started; the others wait for "anything from the others?". The screens and the
    docs now say "your voice", "machines" and "people"; `pointe hub` and `pointe node` work as before. Limits: a person
    invited to a machine can make its agents run commands as that machine's account, cannot approve its permission
    prompts yet, and cannot start a session there. 0.10.2 lifted the last two: the session's owner is asked first, and
    the others may answer after 20 seconds ([docs/multi-machine.md](docs/multi-machine.md#a-shared-machine),
    [SECURITY.md](SECURITY.md#people-on-a-machine)).
  - An old part of Pointe next to a new one fails in one sentence with the command that fixes it

    The first step of Pointe over many machines and several people. A node and its hub each say the oldest and newest
    link protocol they speak, and their features: with none in common the node says which side to update, and the hub
    keeps the machine listed, offline, with the same line. Every script, hook and command says its version to the Pointe
    on its machine (`X-Pointe-Client`), which answers one of another version with `426` and the command. A script prints
    one sentence for any refusal, and a refused permission hook leaves the prompt in the terminal
    ([docs/multi-machine.md](docs/multi-machine.md#versions-an-old-pointe-next-to-a-new-one)).

## 0.9 (beta)

- **0.9.0** (2026-11-26, beta): Pointe runs as a hub on Linux (keys in the login keyring, sessions in tmux, pairing by QR in the terminal); new Claude Code sessions Pointe starts skip permission prompts by default, with a setting to ask first; a request aimed at a session by what it works on goes there, "Pointe." answers "which session?", and "Approved." over Pointe's own question answers it
## 0.8 (beta)

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
