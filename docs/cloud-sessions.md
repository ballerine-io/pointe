# Cloud sessions: what Pointe can and cannot control

Checked 2026-11-21 against the vendors' public docs and terms. These products change often; if something below is out
of date, open an issue.

## The short answer

- **Your own cloud machine works today.** A Linux VM or devbox you run (AWS, Hetzner, anywhere) can run Claude Code,
  Codex or OpenCode and join Pointe as a node, with everything a local session gets: talk to it, reports, approvals.
  See [multi-machine.md](multi-machine.md).
- **Vendor-hosted cloud sessions do not.** Neither Anthropic nor OpenAI offers a public interface that lets an outside
  app read the transcript of, or answer the approvals of, the cloud sessions you run on your own subscription
  (Claude Code on the web, Codex Cloud in ChatGPT). Pointe does not use private endpoints or your browser login to get
  around that: the vendors' terms forbid it, and so do Pointe's own rules.

Pointe needs four things from a session: read its state and transcript, send it a message, receive and answer its
permission requests, and (optionally) start it.

## By surface

| Surface | Read | Send | Approvals | Start | Status for Pointe |
|---|---|---|---|---|---|
| A session on a machine you control, local or cloud VM | Yes | Yes | Yes | Yes | **Supported** (local, or as a node) |
| Claude Code on the web (claude.ai/code), through your own `claude` CLI | No | Yes (`claude -p "…" --cloud <id>`) | No | Yes (`claude --cloud "…"`) | Not supported: no way to read it |
| Claude Code Remote Control | Its sessions run on your machine | | | | **Already supported**: Pointe joins the local session |
| Claude Code background sessions (`claude --bg`, agent view) | Yes | Yes | Yes | n/a | **Already supported** (local) |
| Claude Managed Agents (Claude API, beta) | Yes | Yes | Yes | Yes | Possible later: spawn-only, billed to an API key |
| Codex Cloud, through your own `codex cloud` CLI (experimental) | Status and summary only | No | No | Yes | Not supported |
| Codex remote connections / ChatGPT mobile remote | Their host side is the local Codex app-server | | | | **Already supported**: Pointe joins the local app-server |
| OpenAI Agents API (public beta) | Yes | Yes | No manual approval of shell or file actions | Yes | Possible later, without voice approvals |

"Spawn-only" means Pointe could drive only sessions it starts there itself; it still could not see sessions you started
in the vendor's own app.

## What would change this

- A vendor publishing a read API (transcript or event stream) and an approvals API for subscription cloud sessions.
  Pointe would add a harness adapter for it, under the harness contract in [harnesses.md](harnesses.md).
- A Claude Managed Agents adapter is designed but not built: it would be an opt-in mode with its own API key in the
  Keychain and its own spending limit, separate from your Claude subscription. Track it in [issue #29](https://github.com/ballerine-io/pointe/issues/29).

## Sources (read 2026-11-21)

- Anthropic: [Claude Code in the cloud](https://code.claude.com/docs/en/claude-code-on-the-web),
  [cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging),
  [Remote Control](https://code.claude.com/docs/en/remote-control),
  [agent view](https://code.claude.com/docs/en/agent-view),
  [legal and compliance](https://code.claude.com/docs/en/legal-and-compliance),
  [Managed Agents overview](https://platform.claude.com/docs/en/managed-agents/overview),
  [Managed Agents permission policies](https://platform.claude.com/docs/en/managed-agents/permission-policies),
  [Consumer Terms](https://www.anthropic.com/legal/consumer-terms).
- OpenAI: [Codex CLI commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli),
  [Codex remote connections](https://learn.chatgpt.com/docs/remote-connections),
  [Agents API sessions](https://developers.openai.com/api/docs/guides/agents-api/sessions),
  [Agents API approvals](https://developers.openai.com/api/docs/guides/agents-api/sessions/approvals),
  [Terms of Use](https://openai.com/policies/row-terms-of-use/).
