# Talk to agents: OpenClaw, Hermes Agent, and others

Pointe can talk to agents built on agent frameworks, in the same call as your coding sessions. Pointe is a channel to
the agent, not a replacement for it: the agent keeps its own memory, tools, schedules and approval rules. Design:
[design/agents.md](design/agents.md).

Behind a flag while it is proven: start Pointe with `POINTE_AGENTS=on` (for example `POINTE_AGENTS=on pointe restart`).

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

Approvals: OpenClaw ships with exec approvals off (`tools.exec.ask: off`), so its agent runs commands without asking.
To have each command asked, set `tools.exec.ask` to `on-miss` or `always` in OpenClaw's config. Pointe then reads each
request to you like a session's and answers only your yes or no, once. With nobody answering, OpenClaw's own fallback
decides (deny by default).

## Connect Hermes Agent

1. Turn on Hermes's API server: `API_SERVER_ENABLED=true` and an `API_SERVER_KEY` in its `.env`, then
   `hermes gateway run` (default port 8642).
2. `pointe agent add hermes http://127.0.0.1:8642 --name hermes`, and give the API server key when asked.

Approvals: Hermes's dangerous-command approvals come to you the same way; nobody answering means Hermes denies after
its own timeout.

## Connect any other agent

- **A2A** (Agent2Agent protocol, any agent with an agent card at `/.well-known/agent-card.json`):
  `pointe agent add a2a <its address> --name <name>` with the bearer token it gave you. Tested with OpenClaw's and
  Hermes's A2A servers; Google ADK, LangGraph, Microsoft Agent Framework, BeeAI and Agno document A2A servers too.
- **OpenAI-compatible chat** (an agent served as `/v1/chat/completions`, such as Letta's or Microsoft Agent
  Framework's): `pointe agent add openai <its /v1 address> --name <name> [--agent <model name>]`.

Neither surface carries approvals: the agent's own rules decide, and Pointe says so instead of asking you.

## Manage them

- `pointe agents` lists them and whether each answers.
- `pointe agent remove <name>` takes one out and deletes its saved credential.
- An agent is yours alone: people you invite to this machine do not see it unless you share it (`pointe share <name>`).

## Privacy

What an agent says is transcribed into your call like a session's: it reaches the services your voice uses (your
brain, reader and voice vendors). Pointe says which once, when you connect an agent. Its credential stays in your
Keychain and is sent only to that agent's address.
