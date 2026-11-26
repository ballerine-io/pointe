# Limits

What does not work yet, and what was not measured. Each feature page lists its own limits too.

- **Beta.** Pointe works and is used every day; expect rough edges, and please
  [report them](https://github.com/ballerine-io/pointe/issues).
- **You bring the model keys.** A Claude subscription cannot run Pointe's own models, so it needs an API key billed per
  use, or a 32 GB Mac for fully local mode: [Which keys](install.md#which-keys).
- **Claude Code cannot be interrupted from outside.** "Stop" ends a Claude Code turn at its next tool step, and a
  command that is already running finishes first. Codex and OpenCode stop at once: [Harnesses](harnesses.md).
- **macOS, or Linux as a hub.** A Linux hub was tested in Ubuntu containers: the install, keys in the login keyring,
  the page, a session, a call's microphone audio reaching the hub, pairing and a node. A whole spoken call with a vendor,
  a real phone and Twingate were not tested on Linux: [Linux](linux.md). Windows is not supported.
- **One person's voice.** Everyone paired with a hub (phones, browsers, nodes) acts as its owner, and one call runs at a
  time: a second caller is refused while one talks. Give each person their own hub ([why](linux.md#other-machines-and-other-people)).
- **The Mac app** is `Pointe.dmg`, signed with Developer ID and notarized, the image and the app in it
  ([how](mac-app.md#getting-it)). Its
  first-launch install ran for real into an empty home folder, through the same installer code, but has not yet been
  followed on a fresh Mac account; its screens were checked in a preview. Its
  call, typed words, its microphone's audio reaching Pointe, a request and a brain dump were run against a real daemon
  on one MacBook Pro; AirPods, device changes, the Touch ID sheet and a spoken sentence heard through it in this
  version were not.
- **The iPhone app is on the [App Store](https://apps.apple.com/app/id6838678047)** (beta builds on [TestFlight](https://testflight.apple.com/join/gkRJccpc)). You can also build it from source
  (`pointe apps ios`, [how](iphone-app.md#getting-the-app)); with a free Apple Account such a build opens for 7 days. It was tested on a real iPhone over Twingate, and in the simulator. Without it, the
  page works in a phone browser. Talk to Pointe (the Control, the Action button, the widget) ran in the simulator against
  a stand-in Mac, Control Center and the Home Screen widget included; the Action button and a real microphone are still
  to be tried on a phone. With a free Apple Account the widget is a plain button, with no Mac status (no App Groups).
- **Mostly synthetic evidence.** The benchmarks, the voice lock thresholds and the whisper numbers use synthetic
  voices. Recorded people are used for two things only: a one-word yes or no after a read-out (Speech Commands) and
  pauses and ends of turn in meetings (AMI). Use the voice lock at Approvals, and treat whisper recognition as limited.
- **Real hardware.** Drive mode has not been measured on car hands-free audio. Phone alerts depend on the app being alive
  (there is no push server). Conflict alarms have no live run with real OpenCode or Codex sessions.
- **A request without a short form is read word for word.** Every request can be approved by voice, but a yes counts
  only after the whole request was said (`pointe/guards.py`, `spoken_request`). Known programs in plain pipelines have
  a short form (`pointe/readout.py`); anything else, a compound shell command or an MCP tool call, is read word for
  word, which can take tens of seconds. A request that holds a credential-like value is never read out: it waits for a
  tap on the page, the phone or the terminal.
- **Echo.** On laptop speakers, only Soniox ears have the echo guard; with other ears, use headphones. Known echo cases
  that are not solved are listed in [docs/how-it-works.md](how-it-works.md#echo).
- **Vendor-hosted cloud sessions are out of reach.** Claude Code on the web and Codex Cloud have no public interface to
  read them or answer their approvals, so Pointe cannot join them. A cloud VM you run works, as a node. See
  [docs/cloud-sessions.md](cloud-sessions.md).
- **Code running as you is trusted.** It can read Pointe's token and act as you. See [SECURITY.md](../SECURITY.md#known-limits).
