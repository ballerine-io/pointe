# Talk to agents: OpenClaw, Hermes Agent, and others

Pointe can talk to agents built on agent frameworks, in the same call as your coding sessions. Pointe is a channel to
the agent, not a replacement for it: the agent keeps its own memory, tools, schedules and approval rules. Design:
[design/agents.md](design/agents.md).

It is on by default and does nothing until you connect an agent. Turn it off or on in Settings, Labs, Agents, on
the page, the iPhone or the Mac; the setting is saved on the Mac.
`POINTE_AGENTS=on` or `off` in Pointe's environment decides instead, until Pointe restarts without it, and the switch
says so.

## What you can say

- "Talk to hermes": every turn goes to that agent, and its replies are read back. "Orchestrator mode" leaves it.
- "Ask openclaw to check my calendar for Friday": one request. The reply comes when the agent is done, and waits in
  "what needs me" if you are busy or not on a call. With no call up and alerts on, your phone (or the Mac, or the page)
  shows "openclaw replied", once until you hear or read it; a tap opens the reply.
- "What did hermes say?"
- "Give hermes's answer to openclaw": Pointe reads back what it will pass on and sends it only after your spoken yes.
  Every hop asks. The receiving agent sees it marked as another agent's output.

## Connect OpenClaw

1. Run an OpenClaw gateway (`openclaw gateway run`, or its Docker image) and note its address (default port 18789) and
   its gateway token (`gateway.auth.token`, or `OPENCLAW_GATEWAY_TOKEN`).
2. `pointe agent add openclaw http://127.0.0.1:18789 --name openclaw`, or Settings, Agents, Connect an agent.
   Pointe asks for the token with hidden typing and keeps it in your Keychain.
3. `--agent <id>` picks another of the gateway's agents than its default.

Approvals: OpenClaw runs commands without asking unless you tell it to (its default is `security: full`, `ask: off`).
See "Approvals: a safe default" below.

## Connect Hermes Agent

1. Turn on Hermes's API server: `API_SERVER_ENABLED=true` and an `API_SERVER_KEY` in its `.env`, then
   `hermes gateway run` (default port 8642).
2. `pointe agent add hermes http://127.0.0.1:8642 --name hermes`, and give the API server key when asked.

Approvals: Hermes's dangerous-command approvals come to you the same way; nobody answering means Hermes denies after
its own timeout (300 seconds).

## Connect any other agent

- **A2A** (Agent2Agent protocol, any agent with an agent card at `/.well-known/agent-card.json`):
  `pointe agent add a2a <its address> --name <name>` with the bearer token it gave you. Tested with OpenClaw's and
  Hermes's A2A servers; Google ADK, LangGraph, Microsoft Agent Framework, BeeAI and Agno document A2A servers too.
- **OpenAI-compatible chat** (an agent served as `/v1/chat/completions`, such as Letta's or Microsoft Agent
  Framework's): `pointe agent add openai <its /v1 address> --name <name> [--agent <model name>]`.

Neither surface carries approvals: the agent's own rules decide, and Pointe says so instead of asking you.

## Approvals: a safe default

An agent acts with your accounts, so let it ask before it runs a command. Pointe reads each request to you like a
session's and answers only your spoken yes or no (or a tap with Face ID), for that one command: never "always". Nobody
answering leaves the decision to the agent's own fallback, which denies.

- **OpenClaw:** in its config, set `"tools": {"exec": {"mode": "ask"}}`: commands on OpenClaw's allowlist run, every
  other one asks. Leave `askFallback` unset (deny). Avoid `full` (never asks) and `auto` (a model approves some
  commands instead of you). Older configs say the same with `"security": "allowlist", "ask": "on-miss"`;
  `"ask": "always"` asks for every command, even allowlisted ones. Check the result with
  `openclaw approvals get --gateway`.
- **Hermes:** keep `approvals.mode: manual` in `config.yaml` (its default): dangerous commands ask. `smart` lets a
  model approve the ones it judges low-risk; `off` asks nothing. Not every risky command is flagged by Hermes.
- **A2A and OpenAI-compatible agents** carry no approvals on the wire: the agent's own rules decide, and Pointe says so.

## An agent on another machine

Pointe reaches an agent at any address it can open from this machine:

- **https**, anywhere: `pointe agent add openclaw https://agent.example.com`. A certificate your Mac trusts is needed.
- **Tailscale:** the machine's MagicDNS name or address, plain http is fine because Tailscale encrypts the traffic:
  `http://kite.tail1234.ts.net:18789`, `http://kite:18789` or `http://100.88.12.4:18789`. Tailscale Serve gives the
  same agent an https address.
- **Twingate:** a resource for the agent's port with an alias ending in `.internal` (as in
  [phone/twingate.md](phone/twingate.md)), then `http://kite.<network>.internal:18789`. With another kind of name,
  use https.
- **Your own network:** a private address such as `http://192.168.1.20:8642`.

Plain http to an internet address is refused: the agent's credential goes with every request. The agent must listen on
an address the network reaches, not only its own `127.0.0.1` (OpenClaw: `--bind`; Hermes: `API_SERVER_HOST`). For an
A2A agent, Pointe sends the token only to the address you gave: an agent card that names another host or says `http`
behind https (OpenClaw and Hermes both build it from the request) changes only the path Pointe calls.

## Manage them

- `pointe agents` lists them and whether each answers.
- `pointe agent remove <name>` takes one out and deletes its saved credential.
- An agent is yours alone: people you invite to this machine do not see it unless you share it (`pointe share <name> --shared`).

## Privacy

What an agent says is transcribed into your call like a session's: it reaches the services your voice uses (your
brain, reader and voice vendors). Pointe says which once, when you connect an agent. Its credential stays in your
Keychain and is sent only to that agent's address.
