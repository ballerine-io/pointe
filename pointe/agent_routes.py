"""The daemon's side of agents (docs/design/agents.md): the routes the screens and `pointe agent` use, and each
configured agent registered as a session of its kind. In daemon.py, after the people and the hub are set up:

    AGENTS = agent_routes.install(app, host)

`host` gives: state_dir, registry, join(body) (daemon._join), drop(session) (daemon._drop), people (guests.HostSide),
vendors() (the services transcripts reach), and optionally switched() (daemon: the brain's relay tool follows the
setting and the list). Nothing here
runs with agents off (the setting `agents.on`, or POINTE_AGENTS): no route answers but the list, which says the feature
is off, and no session is registered. `apply()` follows the setting when it changes, without a restart.
"""


import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from loguru import logger

import agents
import harnesses
from harnesses import agent as agent_harness


class Agents:
    def __init__(self, host):
        self.host = host
        self.store = agents.Store(host.state_dir)
        self.disclose: set[str] = set()  # agents added on a screen whose "where its words go" line is not dismissed

    def harness(self, agent):
        return harnesses.get(agent.kind)

    def session(self, agent):
        return self.host.registry.sessions.get(agent.session_id)

    def entry(self, agent) -> dict:
        session, harness = self.session(agent), self.harness(agent)
        state, why = harness.state(session) if session is not None and hasattr(harness, "state") else ("unknown", "")
        return {**agent.public(), "state": state, **({"why": why} if why else {}),
                "approvals": bool(getattr(harness, "approvals", False)),
                **({"session": session.name} if session is not None else {})}

    async def register(self, agent) -> None:
        """Its session, as the daemon registers any: private to the owner until shared (docs/design/agents.md, People)."""
        folder = Path(self.host.state_dir) / "agents" / agent.session_id
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        known = agent.session_id in self.host.registry.sessions
        await self.host.join({"id": agent.session_id, "name": agent.name, "name_given": True, "cwd": str(folder),
                              "harness": agent.kind, "attached": True,
                              "transcript": str(agent_harness.AgentHarness.mirror_path(agent.session_id)),
                              "harness_data": {"agent": agent.name}})
        session = self.session(agent)
        if session is not None and not known and self.host.people is not None:
            await self.host.people.share(session, True)

    async def apply(self) -> None:
        """The setting changed: on, every configured agent joins the voice now; off, each leaves it (its record, its
        credential and agents.json stay, for when it is turned on again)."""
        on = agents.enabled()
        if on:
            harnesses.register_agents()
            agent_harness.CONFIG = self.store.by_session
            await self.register_all()
        else:
            for agent in list(self.store.agents.values()):
                if (session := self.session(agent)) is not None:
                    await harnesses.of(session).leave(session)
                    await self.host.drop(session)
            agent_harness.CONFIG = lambda _sid: None
        self.changed()
        logger.info(f"agents {'on' if on else 'off'}: {len(self.store.agents)} configured")

    def changed(self) -> None:
        """The setting or the list of agents changed: the daemon's brain tools follow."""
        if callable(getattr(self.host, "switched", None)):
            self.host.switched()

    async def register_all(self) -> None:
        for agent in list(self.store.agents.values()):
            try:
                await self.register(agent)
            except Exception as e:
                logger.error(f"agent {agent.name} not registered ({type(e).__name__})")

    async def add(self, body: dict) -> tuple[int, dict | str]:
        kind, name, url = str(body.get("kind") or ""), str(body.get("name") or "").strip(), agents.normalized(body.get("url"))
        if kind not in agents.KINDS:
            return 409, f"Choose the kind of agent: {', '.join(agents.KINDS)}."
        if problem := agents.name_problem(name) or agents.url_problem(url) or agents.secret_problem(body.get("secret")):
            return 409, problem
        if self.store.get(name) is not None:
            return 409, f"An agent is already called {name}. Remove it first, or choose another name."
        if any(s.name.lower() == name.lower() for s in self.host.registry.sessions.values()):
            return 409, f"A session is already called {name}: choose another name."
        agent = agents.Agent(name=name, kind=kind, url=url, agent=str(body.get("agent") or "").strip()[:80])
        secret = str(body["secret"]).strip()
        try:
            await asyncio.wait_for(self.harness(agent).check(agent, secret), 30)
        except agent_harness.AgentError as e:
            return 409, f"Not added: {e}"
        except Exception as e:
            return 409, f"Not added: {agent_harness._offline_words(name, e)}."
        if why := await asyncio.to_thread(agents.save_secret, agent, secret):
            return 409, f"Not added: the credential could not be saved ({why})."
        secret = None
        self.store.put(agent)
        await self.register(agent)
        self.changed()
        self.disclose.add(agent.name)
        logger.info(f"agent {agent.name} added ({kind})")
        return 200, {**self.entry(agent), "vendors_line": agents.vendors_line(self.host.vendors(), agent.name)}

    async def remove(self, name: str) -> bool:
        agent = self.store.remove(name)
        if agent is None:
            return False
        session = self.session(agent)
        if session is not None:
            await harnesses.of(session).leave(session)
            await self.host.drop(session)
        await asyncio.to_thread(agents.delete_secret, agent)
        self.changed()
        self.disclose.discard(agent.name)
        logger.info(f"agent {agent.name} removed")
        return True

    def disclosure(self) -> dict | None:
        """/voice/status `agent_disclosure`: once after an agent is added on a screen, where its words go."""
        name = next(iter(sorted(self.disclose)), None)
        return {"agent": name, "vendors": self.host.vendors(), "line": agents.vendors_line(self.host.vendors(), name)} \
            if name else None


def install(app, host) -> Agents:
    from fastapi import Request
    from fastapi.responses import PlainTextResponse

    from remote import Remote

    hub = Agents(host)
    agent_harness.CONFIG = hub.store.by_session if agents.enabled() else (lambda _sid: None)
    agent_harness.SECRET = agents.read_secret

    def owner(request: Request) -> bool:
        """The page on this machine, a script with its token, or the owner's phone; never a person's key."""
        return not Remote.on_tls_listener(request.scope) or bool(request.scope.get("state", {}).get("pointe_phone"))

    off = PlainTextResponse(agents.OFF, status_code=409)
    refused = PlainTextResponse("forbidden", status_code=403)

    async def body_of(request: Request) -> dict:
        try:
            body = await request.json()
        except ValueError:
            body = {}
        return body if isinstance(body, dict) else {}

    @app.get("/voice/agents")
    async def agents_list(request: Request):
        if not owner(request):
            return refused
        listed = [hub.entry(a) for a in sorted(hub.store.agents.values(), key=lambda a: a.added)] if agents.enabled() else []
        return {"enabled": agents.enabled(), "agents": listed,
                "kinds": [{"kind": k, "title": t, "approvals": bool(getattr(harnesses.get(k), "approvals", False))}
                          for k, (t, _) in agents.KINDS.items()] if agents.enabled() else []}

    @app.post("/voice/agents")
    async def agents_add(request: Request):
        if not owner(request):
            return refused
        if not agents.enabled():
            return off
        status, answer = await hub.add(await body_of(request))
        return answer if status == 200 else PlainTextResponse(answer, status_code=status)

    @app.post("/voice/agents/seen")
    async def agents_seen(request: Request):
        if not owner(request):
            return refused
        hub.disclose.discard(str((await body_of(request)).get("name") or ""))
        return {"ok": True}

    @app.post("/voice/agents/{name}/replies")
    async def agents_replies(name: str, request: Request):
        """What a tap on "<agent> replied" opens: the replies not heard yet, which count as heard once read here. By the
        agent's name or its session's (a renamed one)."""
        if not owner(request):
            return refused
        if not agents.enabled():
            return off
        agent = hub.store.get(name) or next((a for a in hub.store.agents.values()
                                             if (s := hub.session(a)) is not None and s.name == name), None)
        session = hub.session(agent) if agent is not None else None
        if session is None:
            return PlainTextResponse(f"No agent is called {name}.", status_code=404)
        return {"agent": session.name, "replies": harnesses.of(session).read_replies(session)}

    @app.delete("/voice/agents/{name}")
    async def agents_remove(name: str, request: Request):
        if not owner(request):
            return refused
        if not agents.enabled():
            return off
        if not await hub.remove(name):
            return PlainTextResponse(f"No agent is called {name}.", status_code=404)
        return {"ok": True}

    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(_app):
        async with previous(_app):
            if agents.enabled():
                await hub.register_all()
                logger.info(f"agents: {len(hub.store.agents)} configured ({time.strftime('%H:%M')})")
            hub.changed()
            yield

    app.router.lifespan_context = lifespan
    return hub
