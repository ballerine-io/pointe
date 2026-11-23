"""The adapter interface and the parts every agent-backed arm shares.

Events an arm reports (each with a wall time `t`): delivered(session, text), asked(text), said(text),
agent_turn_done(session). The file system stays the primary ground truth.
"""

import asyncio
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .agent import AgentSession, cwd_of


@dataclass
class RunEnv:
    run_id: str
    root: Path                 # /tmp/pccb/<run-id>
    checkout: Path             # the Pointe checkout under test (also the plugin dir of the Pointe arm)
    model: str = "claude-haiku-5-5"
    mode: str = "acceptEdits"
    port_base: int = 9600
    deny_reads: list[Path] = field(default_factory=list)


class Arm:
    name = "base"
    kind = "audio"             # audio | typed | none
    capabilities: frozenset = frozenset()
    wait_after_say = 30.0      # seconds to wait for a delivery or a question after the user stops talking

    def __init__(self, env: RunEnv):
        self.env = env
        self._events: list[dict] = []

    def emit(self, kind: str, **data) -> None:
        self._events.append({"kind": kind, "t": data.pop("t", time.time()), **data})

    def events(self) -> list[dict]:
        out, self._events = self._events, []
        return out

    async def start(self, conv_id: str, repos: dict[str, Path]) -> None: ...
    async def utter(self, clip_id: str, pcm48) -> tuple[float, float]: raise NotImplementedError
    async def typed(self, text: str, sessions: list[str]) -> None: raise NotImplementedError
    async def quiet(self) -> None: ...
    async def idle(self) -> bool: return True
    async def settle(self, timeout: float = 90) -> None: ...
    def versions(self) -> dict: return {}
    def spend(self) -> list[dict]: return []
    def audit(self) -> list[dict]: return []
    def processes(self) -> list[dict]: return []
    def stop_counts(self) -> dict[str, int]: return {}  # finished agent turns per session (the Stop hook)
    async def tick(self) -> None: ...  # called by the turn loop twice a second
    async def stop(self) -> None: ...


class AgentArm(Arm):
    """Four Claude Code sessions, one per repo, launched identically in every arm."""

    plugin = False

    @staticmethod
    def job_dir(repos: dict[str, Path]) -> Path:
        """This run of this conversation's own folder: <root>/<arm>/<conv>-r<n>, the parent of its repos folder."""
        return next(iter(repos.values())).parent.parent

    def session_env(self, name: str) -> dict:
        return {}

    async def start(self, conv_id: str, repos: dict[str, Path]) -> None:
        self.conv_id, self.repos = conv_id, repos
        base = self.job_dir(repos) / "agents"
        self.sessions = {name: AgentSession(name, repo, base / name, self.env.model, self.env.mode,
                                            plugin_dir=self.env.checkout if self.plugin else None,
                                            env=self.session_env(name), deny_reads=self.env.deny_reads,
                                            deny_paths=[r for n, r in repos.items() if n != name])
                         for name, repo in repos.items()}
        for s in self.sessions.values():
            s.start()
        await asyncio.gather(*(asyncio.to_thread(s.wait_ready) for s in self.sessions.values()))

    def processes(self) -> list[dict]:
        """One row per session: its own process and its own /tmp working folder (asserted by the runner)."""
        return [{"session": n, "pid": s.pid, "alive": s.alive(), "cwd": cwd_of(s.pid) if s.pid else None,
                 "repo": os.path.realpath(s.repo), "mode": s.mode_shown()} for n, s in self.sessions.items()]

    async def idle(self) -> bool:
        now = time.time()
        return all(not s.busy() and now - s.activity() > 4 for s in self.sessions.values())

    async def settle(self, timeout: float = 90) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if await self.idle():
                return
            await asyncio.sleep(1)

    def stop_counts(self) -> dict[str, int]:
        return {n: s.stops() for n, s in self.sessions.items()}

    async def tick(self) -> None:
        """A permission dialog left open for 5 s is answered as a person at the keyboard would, the same in every arm
        (recorded): yes when every path it names is inside the session's own repo, Escape otherwise."""
        now = time.time()
        for n, s in self.sessions.items():
            if s.prompt_pending():
                s.prompt_since = s.prompt_since or now
                if now - s.prompt_since > 5:
                    if s.prompt_stays_in_repo():
                        s.approve()
                        self.emit("prompt_approved", session=n)
                    else:
                        s.decline()
                        self.emit("prompt_declined", session=n)
            else:
                s.prompt_since = None

    def type_into(self, name: str, text: str) -> None:
        self.sessions[name].type(text)
        self.emit("delivered", session=name, text=text)

    def spend(self) -> list[dict]:
        rows = []
        for n, s in self.sessions.items():
            u = s.usage()
            if u["api_messages"]:
                rows.append({"vendor": "anthropic", "what": f"agent:{n}", "model": ",".join(u["models"]),
                             "usd": round(u["usd"], 6), "how": "computed", "tokens": u["tokens"]})
        return rows

    def audit(self) -> list[dict]:
        """Tool inputs that name a path outside the session's own repo. `scoring` is True when the path is in the
        checkout's benchmark folder (the answer keys): the turn is excluded. `cross_repo` marks a path in another repo
        of this run (after a misroute the agent looks for the repo it was meant for); it comes after the arm's routing
        decision, edits there are denied, and it is counted per arm, not excluded. Anything else is counted and kept."""
        flagged = []
        run_root = (str(self.env.root), os.path.realpath(self.env.root))
        bench = str(self.env.checkout / "bench" / "conversational")
        for n, s in self.sessions.items():
            repo = (str(s.repo), os.path.realpath(s.repo))
            for call in s.tool_inputs():
                text = str(call["input"])
                for token in re.findall(r"(?<![\w.])/[^\s'\"`;|&()<>]*", text):
                    if token.startswith(repo) or token.startswith("/dev/"):
                        continue
                    if self.plugin and token.startswith(str(self.env.checkout)) and not token.startswith(bench):
                        continue  # the Pointe plugin itself, the one allowed exception
                    flagged.append({"session": n, "tool": call["tool"], "path": token[:120], "t": call.get("t"),
                                    "scoring": token.startswith(bench), "cross_repo": token.startswith(run_root)})
        return flagged

    async def stop(self) -> None:
        for s in getattr(self, "sessions", {}).values():
            s.stop()
