"""A fake arm for the offline tests: no agent, no key, no audio. A policy maps each utterance to an action, and the
arm writes the turn's word into the chosen repo itself, as a perfect agent would."""

import time

from ..core.adapter import Arm


class EchoArm(Arm):
    name = "echo"
    kind = "audio"
    wait_after_say = 2.0

    def __init__(self, env, policy):
        super().__init__(env)
        self.policy = policy  # (clip_id) -> ("send", [sessions], word) | ("ask", text) | ("none",)

    async def start(self, conv_id, repos):
        self.repos = repos

    async def utter(self, clip_id, pcm48):
        now = time.time()
        action = self.policy(clip_id)
        if action[0] == "send":
            for name in action[1]:
                with (self.repos[name] / "NOTES.md").open("a") as f:
                    f.write(f"{action[2]}\n")
                self.emit("delivered", session=name, text=action[2])
        elif action[0] == "ask":
            self.emit("asked", text=action[1])
        return now, now
