# Security reviews

Pointe runs with your model keys, hears your microphone, and can approve your coding agents' permission prompts. We
review its security on a schedule and publish each review here: what was looked at, what was found, and what we did
about each finding.

## Cadence

This schedule starts after Pointe's public launch:

- **Weekly:** a review of the code that changed that week (`tools/security_review.sh --since <last week's commit>`), and
  one of the five areas below in full, in rotation, so each area is read whole about every five weeks.
- **Before a tag:** a change to a security boundary is reviewed before the release that carries it is tagged. The
  boundaries are the listeners and their authentication, pairing, what a spoken word or a tap can approve, how keys
  reach processes, and the install path.
- **Quarterly:** all five areas in full.

Until launch, reviews run when a boundary changes. The first one covered all five areas (2026-11-23, below).

## Method

Each review is up to five focused passes by Claude Mythos 5.2 through Claude Code, run by `tools/security_review.sh`. Each pass
reads a clean checkout of one commit with read tools only (`Read`, `Grep`, `Glob`, and `git log`, `git show`, `rg`, `ls`
through the shell): it cannot edit files, run code or reach the network through a tool. It starts from the threat model
in [SECURITY.md](../../../SECURITY.md), and reports each issue with file and line evidence, a scenario, a severity and a
fix, plus what it checked and found sound, and what it did not cover.

| Area | Focus |
|---|---|
| `network-pairing` | The loopback server's checks, the TLS phone listener, pairing, the hub and node link |
| `approvals-voice` | What a spoken word or a tap can approve or send, read-backs, the voice lock, meeting mode, night shift |
| `secrets-supply` | How keys reach processes, logs, the install path, plugin hooks and commands, pins, the egress list |
| `web-page` | The page the daemon serves: HTML insertion, event handling, framing, storage, the phone browser path |
| `apple-apps` | The iPhone and Mac apps: pinning, pairing storage, the Keychain, deep links, Face ID and Touch ID, entitlements |

The model's reports are leads, not verdicts. A maintainer checks each finding against the code and marks it **fixed**
(with a test that failed before the fix), **by design** (with the reason), **accepted** (a known limit, with the
reason), or **not reproducible**. Fixes are reviewed again by the same passes before release. A review is one input
next to the tests in `tests/test_security.py` and the rest of the suite, outside reports, and our own reading; it is not
a guarantee that no issue remains.

## Disclosure

A published review gives the details of a finding only once it is fixed in a released version. A finding that is open
or accepted is described at the level of what it affects and what limits it. To report an issue, use GitHub's private
vulnerability reporting on this repository or write to security@ballerine.com, as [SECURITY.md](../../../SECURITY.md)
says.

## Run it yourself

You need Claude Code signed in with access to the model.

```
tools/security_review.sh                          # all five areas, against HEAD
tools/security_review.sh --ref v0.8.0 web-page   # one area, against a release
tools/security_review.sh --since v0.8.0           # only what changed since a release
tools/security_review.sh --model <model id>       # another model
```

Reports are written to `.security-reviews/<date>/<area>.md` (not committed: they can describe open issues). Set
`CLAUDE_CONFIG_DIR` to run under another Claude Code account. Results vary from run to run; a finding the model does not
repeat is not thereby fixed.

## Reviews

| Date | Version reviewed | Model | Report |
|---|---|---|---|
| 2026-11-23 | A pre-release build (1.21.0), fixes re-reviewed; fixed in pre-release 1.23.1, so in 0.8.0 | Claude Mythos 5.2 (`claude-mythos-5-2`) | [2026-11-23-mythos.md](2026-11-23-mythos.md) |
