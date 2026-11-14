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
        return {**self.inner.capabilities(), "side_questions": False}  # no fork on the node: the reader answers

    def alive(self, session: Session) -> bool:
        return self.hub.alive(session)

    def transcript_path(self, session: Session) -> str:
        return self.hub.transcript_path(session)

    def watch(self, session: Session, feed: Feed):
        from sessions import follow_transcript

        return [follow_transcript(session, feed, lambda: None)]

    async def send(self, session: Session, text: str) -> bool:
        return await self.hub.send(session, text)

    def noise(self, text: str) -> str:
        return self.inner.noise(text)

    async def leave(self, session: Session) -> None:
        await self.hub.leave(session)
