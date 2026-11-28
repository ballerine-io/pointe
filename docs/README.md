# Pointe documentation

Pointe is a voice layer for your coding agents. You talk to all your coding-agent sessions by voice: ask what
each one did, switch by saying its name, and answer permission prompts out loud, under rules enforced in code. Pointe works with
Claude Code, OpenCode and Codex, and runs on your Mac with your own model keys, or with models on the Mac.

## Getting started

- [Getting started](getting-started.md): install, the first setup, the first call, and what joining a session means.
- [Install](install.md): what Pointe installs, the free and cheap ways in, and how to remove it.
- [The Mac app](mac-app.md): the call in the menu bar and a native window.
- [Linux](linux.md): a Linux machine as the hub, keys in the login keyring, reaching it, and who can connect.
- [Compared to other tools](comparison.md): Happy, Paseo, the built-in voices and the phone remotes, and where Pointe differs.
- [Limits](limits.md): what does not work yet, and what was not measured.

## Connect your phone

- [Connect your phone](phone.md): which route to use, pairing, the phone's browser, and troubleshooting.
- Step by step: [Wi-Fi](phone/wifi.md), [Tailscale](phone/tailscale.md), [Twingate](phone/twingate.md),
  [Cloudflare Tunnel with Access](phone/cloudflare.md).
- [The iPhone app](iphone-app.md): the App Store, TestFlight or a build from source, alerts and the Apple Watch.

## Models and setups

- [Models and setups](models.md): the roles, the six setups, keys, choosing models by hand, Azure OpenAI, local models.
- [Setups](setups.md): each setup's vendors, measured results, cost and where your words go.
- [Benchmarks](benchmarks.md): how each default was chosen.

## Architecture

- [Architecture](architecture.md): the components, the data flows, where state lives, and the trust boundaries.
- [How it works](how-it-works.md): the call pipeline and the rules enforced in code, in detail.
- [Harnesses](harnesses.md): Claude Code, OpenCode and Codex, and how to add another.
- [Agents](agents.md): talk to OpenClaw, Hermes Agent and any A2A or OpenAI-compatible agent in the same call (behind
  `POINTE_AGENTS=on`).
- [Machines and people](multi-machine.md): sessions on your other Macs and Linux machines in the same call, and a
  machine several people share, each from their own voice.
- [Cloud sessions](cloud-sessions.md): what Pointe can and cannot reach in vendor-hosted sessions.

## Features

- [Features](features/README.md): every feature in one line, and how to use each by voice, on the page, on the iPhone
  and on the Mac.

## Contributing

- [Contributing](../CONTRIBUTING.md): development setup, the tests, the repository layout, and how to propose a change.
- [Releasing](releasing.md): how a version is cut.
- [Security](../SECURITY.md): the threat model, and how to report a vulnerability.

## Why Ballerine built this

Ballerine's engineers run several coding-agent sessions at once, and built Pointe for their own work. Ballerine is not
a developer-tools company and does not sell Pointe. It is shared because it is useful.

## Support

Pointe is community-supported, on a best-effort basis, with no SLA. Ask questions in
[Discussions → Q&A](https://github.com/ballerine-io/pointe/discussions/categories/q-a), propose features in
[Discussions → Ideas](https://github.com/ballerine-io/pointe/discussions/categories/ideas), and report bugs in
[GitHub issues](https://github.com/ballerine-io/pointe/issues). Report a vulnerability privately, never in an issue:
[GitHub private vulnerability reporting](https://github.com/ballerine-io/pointe/security/advisories/new) or
security@ballerine.com ([SECURITY.md](../SECURITY.md)).
