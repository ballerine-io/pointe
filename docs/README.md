# Pointe documentation

Pointe is a conversational layer for your coding agents. You talk to all your coding-agent sessions by voice: ask what
each one did, switch by saying its name, and answer permission prompts out loud, under rules enforced in code. The
practice is conversational engineering; "convo coding", for short. Pointe works with Claude Code, OpenCode and Codex,
and runs on your Mac with your own model keys, or with models on the Mac.

## Getting started

- [Getting started](getting-started.md): install, the first setup, the first call, and what joining a session means.
- [Install](install.md): what Pointe installs, the free and cheap ways in, and how to remove it.
- [The Mac app](mac-app.md): the call in the menu bar and a native window.

## Connect your phone

- [Connect your phone](phone.md): which route to use, pairing, the phone's browser, and troubleshooting.
- Step by step: [Wi-Fi](phone/wifi.md), [Tailscale](phone/tailscale.md), [Twingate](phone/twingate.md),
  [Cloudflare Tunnel with Access](phone/cloudflare.md).
- [The iPhone app](iphone-app.md): building it from source until it is in the App Store, alerts and the Apple Watch.

## Models and setups

- [Models and setups](models.md): the roles, the six setups, keys, choosing models by hand, Azure OpenAI, local models.
- [Setups](setups.md): each setup's vendors, measured results, cost and where your words go.
- [Benchmarks](benchmarks.md): how each default was chosen.

## Architecture

- [Architecture](architecture.md): the components, the data flows, where state lives, and the trust boundaries.
- [How it works](how-it-works.md): the call pipeline and the rules enforced in code, in detail.
- [Harnesses](harnesses.md): Claude Code, OpenCode and Codex, and how to add another.
- [Machines](multi-machine.md): sessions on your other Macs and Linux machines in the same call.
- [Cloud sessions](cloud-sessions.md): what Pointe can and cannot reach in vendor-hosted sessions.

## Features

- [Features](features/README.md): every feature in one line, and how to use each by voice, on the page, on the iPhone
  and on the Mac.

## Contributing

- [Contributing](../CONTRIBUTING.md): development setup, the tests, the repository layout, and how to propose a change.
- [Releasing](../RELEASING.md): how a version is cut.
- [Security](../SECURITY.md): the threat model, and how to report a vulnerability.
