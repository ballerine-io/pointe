"""What every agent-framework harness shares (docs/design/agents.md): an agent is a session whose record is a mirror
Pointe writes, whose turns run in the background, and whose replies are heard when the user is free.

A kind (openclaw.py, hermes.py, a2a.py, openai_chat.py) provides three things: `submit` (hand the agent one message;
raises AgentError with words for the user when it cannot), `wait` (until the reply, raising AgentError for a failed
turn), and optionally `stop` and `health`. Everything else is here: the mirror, the unheard replies, approvals' shape,
the restart of a turn that was running when the daemon stopped.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from loguru import logger

from .base import HOST, Harness, finished_tag

if TYPE_CHECKING:
    from sessions import Feed, Session

# Set by the daemon (agents_host.install): session id -> its agents.Agent, or None when it is no longer configured.
CONFIG: Callable[[str], object] = lambda session_id: None  # noqa: E731
SECRET: Callable[[object], str | None] = lambda agent: None  # noqa: E731
RELAY_MARK = "[Relayed by the user's voice assistant on the user's spoken yes"
REPLY_CAP = 200_000  # characters of one reply kept in the record; the reader digests it for the voice
HEALTH_EVERY_SECS = 30.0
UNHEARD = "a reply you have not heard yet"


class AgentError(Exception):
    """A turn that could not be handed over or did not finish. Its text is fixed words for the user."""


@dataclass
class Reply:
    text: str
    tools: list[dict] = field(default_factory=list)  # [{name, input}] the agent reported using, in order


class AgentHarness(Harness):
    """One kind of agent. Subclasses set name, label, agent, the capability flags, and implement submit and wait."""

    attach = False
    spawn = False
    starts = False
    side_questions = False  # "by the way" goes to the transcript reader over the mirror
    joins_mid_turn = False
    permission_deadline = 280.0
    framework = True  # an agent built on an agent framework: no folder, no terminal, reached over its own surface

    def __init__(self) -> None:
        self._running: dict[str, dict[str, asyncio.Task]] = {}  # session id -> turn id -> its task
        self._health: dict[str, tuple[float, str]] = {}  # session id -> (checked at, "" when it answers, else why not)
        self._resumed: set[str] = set()

    # ---------- what the daemon asks ----------

    def config(self, session: Session):
        return CONFIG(session.id)

    def alive(self, session: Session) -> bool:
        return self.config(session) is not None  # offline is a state, not a reason to drop it

    def title(self, session: Session) -> str | None:
        return None

    def capabilities(self) -> dict:
        return {**super().capabilities(), "agent_framework": True}

    def state(self, session: Session) -> tuple[str, str]:
        """("online" | "offline" | "unknown", why not in fixed words)."""
        checked = self._health.get(session.id)
        if checked is None:
            return "unknown", ""
        return ("online", "") if not checked[1] else ("offline", checked[1])

    @staticmethod
    def mirror_path(session_id: str) -> Path:
        state = HOST.state_dir or Path(os.environ.get("CLAUDE_VOICE_STATE", Path.home() / ".claude-voice"))
        return Path(state) / "harness" / "agents" / f"{session_id}.jsonl"

    async def probe(self, session: Session) -> None:
        """From the daemon's liveness loop: a turn that ran when the daemon stopped is waited on again (once), the
        agent's health is checked every HEALTH_EVERY_SECS, and an unheard reply shows in "what needs me"."""
        if session.id not in self._resumed:
            self._resumed.add(session.id)
            for handle in list((session.harness_data or {}).get("pending") or []):
                self._spawn(session, handle)
        if session.followed and session.followed_to and session.followed_to[0] == str(self.mirror_path(session.id)):
            session.harness_data["heard"] = session.followed_to[1]
        elif self._unheard(session) and not session.needs:
            session.needs = {"need": UNHEARD, "unblock": f"what did {session.name} say"}
        checked = self._health.get(session.id)
        if checked and time.time() - checked[0] < HEALTH_EVERY_SECS:
            return
        agent = self.config(session)
        if agent is None:
            return
        try:
            why = await asyncio.wait_for(self.health(session, agent), 3.5)
        except asyncio.TimeoutError:
            why = f"{session.name} did not answer in time"
        except Exception as e:
            why = _offline_words(session.name, e)
        self._health[session.id] = (time.time(), why or "")

    def watch(self, session: Session, feed: Feed):
        from brief import FINAL_MARK
        from sessions import follow_transcript

        async def run():
            path = self.mirror_path(session.id)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.touch(mode=0o600, exist_ok=True)
            offset = min(int((session.harness_data or {}).get("heard") or 0), path.stat().st_size)
            with path.open() as f:
                f.seek(offset)
                for line in f.read().splitlines():
                    text = _final_text(line)
                    if text is not None:  # a reply that came while no call was up: the news of this call
                        await feed(session, f"{finished_tag(self.label)} {FINAL_MARK}{text}", True)
                offset = f.tell()
            session.harness_data["heard"] = offset
            if session.needs and session.needs.get("need") == UNHEARD:
                session.needs = None
            session.followed_to = (str(path), offset, time.time())  # the follower goes on from here, not from the end
            try:
                await follow_transcript(session, feed, lambda: None)
            finally:
                if session.followed_to and session.followed_to[0] == str(path):
                    session.harness_data["heard"] = session.followed_to[1]

        return [run()]

    async def send(self, session: Session, text: str, anyway: bool = False, relay_depth: int = 0) -> bool:
        """Hand the agent the user's words and return: the reply comes later, written to the mirror. False, with
        `turned_down` saying why in fixed words, when the agent could not take it."""
        from sessions import voice_message

        agent = self.config(session)
        if agent is None:
            return False
        secret = await asyncio.to_thread(SECRET, agent)
        if not secret:
            return self._refused(session, f"Not sent. Pointe could not read {session.name}'s credential from the "
                                          f"Keychain: connect it again in Settings, Agents.")
        message = voice_message(text)
        turn = uuid.uuid4().hex[:12]
        try:
            handle = await asyncio.wait_for(self.submit(session, agent, secret, message, turn), 30)
        except asyncio.TimeoutError:
            return self._refused(session, f"Not sent. {session.name} did not take the request in 30 seconds.")
        except AgentError as e:
            self._health[session.id] = (time.time(), str(e))
            return self._refused(session, f"Not sent. {e}")
        except Exception as e:
            words = _offline_words(session.name, e)
            self._health[session.id] = (time.time(), words)
            return self._refused(session, f"Not sent. {words}.")
        self._health[session.id] = (time.time(), "")
        handle = {**handle, "turn": turn, "relay": relay_depth, "at": time.time()}
        self._write(session, {"type": "user", "message": {"role": "user", "content": message}, "pointeTurn": turn,
                              "pointeRelay": relay_depth})
        # `_` keys stay in memory: a reply already in hand is not written to sessions.json
        session.harness_data.setdefault("pending", []).append({k: v for k, v in handle.items() if not k.startswith("_")})
        _save()
        session.busy = True
        self._spawn(session, handle)
        return True

    async def interrupt(self, session: Session) -> bool:
        running = list((session.harness_data or {}).get("pending") or [])
        if not running:
            return False
        agent = self.config(session)
        if agent is None:
            return False
        secret = await asyncio.to_thread(SECRET, agent)
        stopped = False
        for handle in running:
            try:
                stopped |= bool(await self.stop(session, agent, secret or "", handle))
            except Exception as e:
                logger.info(f"agent {session.name}: stop failed ({type(e).__name__})")
        return stopped

    async def leave(self, session: Session) -> None:
        for task in (self._running.pop(session.id, {}) or {}).values():
            task.cancel()

    def last_reply(self, session: Session) -> tuple[str, int] | None:
        """The agent's last finished reply, verbatim, and its relay depth: what a relay passes on."""
        path = self.mirror_path(session.id)
        try:
            lines = path.read_text().splitlines()
        except OSError:
            return None
        for line in reversed(lines):
            entry = _entry(line)
            if entry and entry.get("pointeAgentReply") and not entry.get("pointeError"):
                return _final_text(line) or "", int(entry.get("pointeRelay") or 0)
        return None

    # ---------- what a kind implements ----------

    async def submit(self, session: Session, agent, secret: str, message: str, turn: str) -> dict:
        """Hand over one message; return a JSON-able handle `wait` can pick up again after a restart."""
        raise NotImplementedError

    async def wait(self, session: Session, agent, secret: str, handle: dict) -> Reply:
        raise NotImplementedError

    async def stop(self, session: Session, agent, secret: str, handle: dict) -> bool:
        return False

    async def health(self, session: Session, agent) -> str:
        """"" when the agent answers (without spending a model turn), else why not in fixed words."""
        return ""

    # ---------- the record ----------

    def _spawn(self, session: Session, handle: dict) -> None:
        running = self._running.setdefault(session.id, {})
        if handle["turn"] in running:
            return
        running[handle["turn"]] = asyncio.get_running_loop().create_task(self._finish(session, handle))

    async def _finish(self, session: Session, handle: dict) -> None:
        agent = self.config(session)
        try:
            if agent is None:
                return
            secret = await asyncio.to_thread(SECRET, agent) or ""
            reply = await self.wait(session, agent, secret, handle)
            for tool in reply.tools:
                self._write(session, {"type": "assistant", "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "id": uuid.uuid4().hex[:12], "name": str(tool.get("name") or "tool"),
                     "input": tool.get("input") if isinstance(tool.get("input"), dict) else {}}]}})
            self.reply(session, reply.text or f"{session.name} finished without a reply.", handle)
        except asyncio.CancelledError:
            raise
        except AgentError as e:
            self.reply(session, f"No answer from {session.name}: {e}", handle, error=True)
        except Exception as e:
            logger.warning(f"agent {session.name}: turn {handle.get('turn')} failed ({type(e).__name__})")
            self.reply(session, f"No answer from {session.name}: {_offline_words(session.name, e)}.", handle, error=True)
        finally:
            self._running.get(session.id, {}).pop(handle.get("turn"), None)
            pending = (session.harness_data or {}).get("pending") or []
            session.harness_data["pending"] = [h for h in pending if h.get("turn") != handle.get("turn")]
            session.busy = bool(session.harness_data["pending"])
            _save()

    def reply(self, session: Session, text: str, handle: dict | None = None, error: bool = False) -> None:
        """A finished reply into the record: the follower reports it during a call; with none up, it waits as unheard.
        Also for a reply the agent sent on its own (`handle` None: a scheduled job announcing into the conversation)."""
        text = str(text).strip()
        if len(text) > REPLY_CAP:
            text = text[:REPLY_CAP] + "\n\n[cut here: the reply was longer]"
        self._write(session, {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}],
                              "stop_reason": "end_turn"}, "pointeAgentReply": True,
                              "pointeTurn": (handle or {}).get("turn", ""), "pointeRelay": int((handle or {}).get("relay") or 0),
                              **({"pointeError": True} if error else {}), **({} if handle else {"pointeUnasked": True})})
        if not session.followed:
            session.needs = {"need": UNHEARD, "unblock": f"what did {session.name} say"}

    def _write(self, session: Session, entry: dict) -> None:
        path = self.mirror_path(session.id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        entry = {**entry, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"}
        with path.open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        path.chmod(0o600)

    def _unheard(self, session: Session) -> bool:
        path = self.mirror_path(session.id)
        try:
            size = path.stat().st_size
        except OSError:
            return False
        heard = int((session.harness_data or {}).get("heard") or 0)
        if size <= heard:
            return False
        with path.open() as f:
            f.seek(heard)
            return any(_final_text(line) is not None for line in f.read().splitlines())

    def _refused(self, session: Session, line: str) -> bool:
        session.turned_down = {"why": "agent", "line": line, "at": time.time()}
        logger.info(f"agent {session.name}: {line}")
        return False

    async def hold(self, session: Session, command: str, description: str, gone=None) -> str | None:
        """An approval the agent's framework asks a human for: put to the user like any session's prompt. "allow",
        "deny", or None when nobody answered (the framework's own timeout then decides: deny, for both)."""
        if HOST.hold_permission is None:
            return None
        tool_input = {"command": command, "description": description} if command else {"description": description}
        return await HOST.hold_permission(session, "Bash" if command else "Agent action", tool_input, gone)


def _entry(line: str) -> dict | None:
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    return entry if isinstance(entry, dict) else None


def _final_text(line: str) -> str | None:
    entry = _entry(line)
    if not entry or entry.get("type") != "assistant":
        return None
    message = entry.get("message") or {}
    if message.get("stop_reason") != "end_turn":
        return None
    return " ".join(str(b.get("text") or "") for b in message.get("content") or [] if isinstance(b, dict)).strip()


def _offline_words(name: str, error: Exception) -> str:
    """Fixed words for a failure: never the exception's own text, which may quote a URL with a credential or a reply."""
    import aiohttp

    if isinstance(error, aiohttp.ClientResponseError):
        if error.status in (401, 403):
            return f"{name} refused Pointe's credential: connect it again with a current one"
        return f"{name} answered with an error ({error.status})"
    if isinstance(error, (aiohttp.ClientConnectorError, ConnectionError, OSError)):
        return f"{name} is not reachable: is it running?"
    if isinstance(error, (asyncio.TimeoutError, aiohttp.ServerTimeoutError)):
        return f"{name} did not answer in time"
    return f"{name} failed ({type(error).__name__})"


def _save() -> None:
    save = getattr(HOST, "save_sessions", None)
    if save:
        save()
