"""The shared body of the two reference voice arms: Soniox ears on the user's audio, a policy that turns one transcript
into actions on the pty, and local Kokoro speaking the agent's final message of each turn (first 600 characters)."""

import threading
import time

import numpy as np

from core import voice_io
from core.adapter import Event, SpendRow, now
from core.ledger import soniox_usd
from adapters.base import PtyArm

SPOKEN_CHARS = 600
MOUTH_VOICE = "af_heart"  # the reference arms' own voice; Whisper scores it like every other adapter's output


class SpokenRef(PtyArm):
    capabilities = frozenset({"audio_in", "text_in", "speech_out", "approvals", "sessions", "interrupt"})

    def start(self, sessions, env):
        self.ears = voice_io.SonioxEars()
        self.mouth = voice_io.LocalMouth(MOUTH_VOICE)
        self.last_action = "none"
        self._spoken_turns: set[float] = set()
        self._watch_stop = False
        super().start(sessions, env)
        self._started = now()
        threading.Thread(target=self._speak_turns, daemon=True).start()

    # ---------- speech in ----------

    def say(self, pcm: bytes, rate: int) -> tuple[float, float]:
        arr = np.frombuffer(pcm, dtype=np.int16) if isinstance(pcm, bytes) else pcm
        known = threading.Event()
        box = {}

        def started(speech):
            box["speech"] = speech
            known.set()

        def run():
            heard = self.ears.hear(arr, on_start=started)
            self._events.append(Event(heard["final_at"], "heard", self.session, heard["text"],
                                      {"error": heard["error"]}))
            try:
                acts = self.policy(heard["text"])
            except Exception as e:  # recorded, never silent: the run is then scored as what happened
                self._events.append(Event(now(), "action", self.session, f"policy error: {type(e).__name__}: {e}"[:300]))
                self.policy_errors = getattr(self, "policy_errors", 0) + 1
                return
            for act in acts:
                self._do(act)

        threading.Thread(target=run, daemon=True).start()
        known.wait(15)
        start, end = box.get("speech", (now(), now()))
        wait = end - now()
        if wait > 0:
            time.sleep(wait)
        return start, end

    def _do(self, act: tuple) -> None:
        kind = act[0]
        at = now()
        if kind == "escape":
            self.agent.key("escape")
            self._events.append(Event(at, "stopped", self.session, "", {"how": self.name}))
            time.sleep(0.6)  # Claude Code takes the key before the next one
        elif kind == "type":
            self.agent.type(act[1])
            self._events.append(Event(at, "delivered", self.session, act[1], {"how": self.name}))
        elif kind == "say":
            self.mouth.say(act[1])
            self._events.append(Event(at, "asked", self.session, act[1]))
        elif kind == "approve":
            self.agent.key("enter")
            self._events.append(Event(at, "approval_decision", self.session, "allow", {"how": self.name}))
        elif kind == "deny":
            self.agent.key("escape")
            self._events.append(Event(at, "approval_decision", self.session, "deny", {"how": self.name}))
        self.last_action = kind

    def policy(self, text: str) -> list[tuple]:
        raise NotImplementedError

    def working(self) -> bool:
        return self.agent.turn_done_at(self._started) is None and bool(self.agent.lines)

    # ---------- speech out ----------

    def _speak_turns(self) -> None:
        while not self._watch_stop:
            done = self.agent.turn_done_at(self._started) if self.agent else None
            if done is not None and done not in self._spoken_turns:
                self._spoken_turns.add(done)
                text = self.agent.final_text(done)[:SPOKEN_CHARS]
                if text.strip():
                    self.mouth.say(text)
                    self._events.append(Event(now(), "said", self.session, text))
            time.sleep(0.05)

    def speech(self):
        from core import audio

        return [(a, b, audio.cut(self.mouth.frames, a, b).tobytes()) for a, b in audio.spans(self.mouth.frames)]

    def frames(self):
        return self.mouth.frames

    def speaking(self) -> bool:
        return self.mouth.busy()

    def spend(self):
        return super().spend() + [SpendRow("soniox:ears", round(soniox_usd(self.ears.stream_seconds), 6), "computed",
                                           f"{self.ears.stream_seconds:.1f} stream seconds")]

    def versions(self):
        import vendors

        return {**super().versions(), "ears": f"soniox:{vendors.SONIOX_RT_MODEL}", "mouth": f"local:kokoro-82m:{MOUTH_VOICE}"}

    def stop(self):
        self._watch_stop = True
        self.mouth.close()
        super().stop()
