"""The floor: starts the four sessions and does nothing."""

from ..core.adapter import AgentArm


class NullArm(AgentArm):
    name = "null"
    kind = "none"
    wait_after_say = 1.0

    async def utter(self, clip_id, pcm48):
        return 0.0, 0.0
