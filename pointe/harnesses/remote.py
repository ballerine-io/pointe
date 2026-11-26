"""A session on another machine, driven over its node's link (docs/design/multi-machine.md, "RemoteHarness").

harnesses.of(session) returns one of these around the session's own adapter when `session.machine` is set
(hub_nodes.install registers it with harnesses.set_remote). The inner adapter describes the harness: label, agent,
noise, the permission deadline, so badges, feed tags and the brief are unchanged. The hub reaches the machine: the
node runs the real adapter there. Its pid is the node's, so nothing here is ever a pid check."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Harness

if TYPE_CHECKING:
    from sessions import Feed, Session


class RemoteHarness(Harness):
    def __init__(self, hub, inner: Harness) -> None:
        self.hub, self.inner = hub, inner
        self.name, self.label, self.agent = inner.name, inner.label, inner.agent
        self.approvals, self.attach, self.spawn = inner.approvals, inner.attach, inner.spawn
        self.joins_mid_turn, self.permission_deadline = inner.joins_mid_turn, inner.permission_deadline

    def capabilities(self) -> dict:
        # No fork on the node (the reader answers), and no stop: the link carries no interrupt yet.
        return {**self.inner.capabilities(), "side_questions": False, "interrupt": None}

    def alive(self, session: Session) -> bool:
        return self.hub.alive(session)

    def transcript_path(self, session: Session) -> str:
        return self.hub.transcript_path(session)

    def watch(self, session: Session, feed: Feed):
        from sessions import follow_transcript

        return [follow_transcript(session, feed, lambda: None)]

    async def send(self, session: Session, text: str, anyway: bool = False) -> bool:
        """False also when the machine refused it: why is then on `session.turned_down` (hub_nodes.Hub.send).
        `anyway`: deliver although the session works on another person's request."""
        return await self.hub.send(session, text, anyway=True) if anyway else await self.hub.send(session, text)

    def noise(self, text: str) -> str:
        return self.inner.noise(text)

    async def answer(self, session: Session, request_id: str, verdict: str, how: str, spoken: str | None) -> bool:
        """`permission.answer` to the node; whether its re-check took it (how: voice | tap | notification)."""
        from loguru import logger

        ok, why = await self.hub.answer(session, request_id, verdict, how, spoken)
        if not ok:
            logger.info(f"{session.name} on {session.machine}: {verdict} by {how} not taken ({why})")
        return ok

    async def leave(self, session: Session) -> None:
        await self.hub.leave(session)
