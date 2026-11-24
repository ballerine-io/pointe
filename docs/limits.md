# Limits

What does not work yet, and what was not measured. Each feature page lists its own limits too.

- **Beta.** Pointe works and is used every day; expect rough edges, and please
  [report them](https://github.com/ballerine-io/pointe/issues).
- **You bring the model keys.** A Claude subscription cannot run Pointe's own models, so it needs an API key billed per
  use, or a 32 GB Mac for fully local mode: [Which keys](install.md#which-keys).
- **Claude Code cannot be interrupted from outside.** "Stop" ends a Claude Code turn at its next tool step, and a
  command that is already running finishes first. Codex and OpenCode stop at once: [Harnesses](harnesses.md).
- **macOS only.** On Linux the daemon starts, but no real call has been made there. Windows is not supported.
- **The Mac app** is `Pointe.dmg`, signed with Developer ID and notarized, the image and the app in it
  ([how](mac-app.md#getting-it)). Its
  first-launch install ran for real into an empty home folder, through the same installer code, but has not yet been
  followed on a fresh Mac account; its screens were checked in a preview. Its
  call, typed words, its microphone's audio reaching Pointe, a request and a brain dump were run against a real daemon
  on one MacBook Pro; AirPods, device changes, the Touch ID sheet and a spoken sentence heard through it in this
  version were not.
- **The iPhone app is in a [TestFlight beta](https://testflight.apple.com/join/gkRJccpc)**, not the App Store yet. You can also build it from source
  (`pointe apps ios`, [how](iphone-app.md#getting-the-app)); with a free Apple Account such a build opens for 7 days. It was tested on a real iPhone over Twingate, and in the simulator. Without it, the
  page works in a phone browser. Talk to Pointe (the Control, the Action button, the widget) ran in the simulator against
  a stand-in Mac, Control Center and the Home Screen widget included; the Action button and a real microphone are still
  to be tried on a phone. With a free Apple Account the widget is a plain button, with no Mac status (no App Groups).
- **Synthetic evidence.** The benchmarks, the voice lock thresholds and the whisper numbers use synthetic voices. No
  bench on recorded people has been run, so use the voice lock at Approvals, and treat whisper recognition as limited.
- **Real hardware.** Drive mode has not been measured on car hands-free audio. Phone alerts depend on the app being alive
  (there is no push server). Conflict alarms have no live run with real OpenCode or Codex sessions.
- **Approvals by voice cover plain commands.** Pointe reads out only known programs in plain pipelines (`pointe/readout.py`).
  A compound shell command (`pwd; ls | head`, an `if [ ... ]` test, `printf ... > file`), a web fetch or a tool call
  from an MCP server is not read out: it waits for a tap on the page, the phone or the terminal. With no screen in
  reach, such a request waits until you have one.
- **Echo.** On laptop speakers, only Soniox ears have the echo guard; with other ears, use headphones. Known echo cases
  that are not solved are listed in [docs/how-it-works.md](how-it-works.md#echo).
- **Vendor-hosted cloud sessions are out of reach.** Claude Code on the web and Codex Cloud have no public interface to
  read them or answer their approvals, so Pointe cannot join them. A cloud VM you run works, as a node. See
  [docs/cloud-sessions.md](cloud-sessions.md).
- **Code running as you is trusted.** It can read Pointe's token and act as you. See [SECURITY.md](../SECURITY.md#known-limits).
