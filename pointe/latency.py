"""Where the time of one reply goes: the stages between the user's last word and the first sound of the answer, one line
per turn in the log (`turn timing: {...}`). No words are kept, only times. tests/e2e/latency.py reads the lines."""

import json

# In the order they happen. Each is stamped once per turn, the first time it happens.
STAGES = ("last_word",  # the user's last word ended (the ears' own word clock; the voice detector's stop without one)
          "stt_final",  # the final transcript of those words arrived
          "settled",  # the turn was taken: the settle time passed, the echo and the voice lock judged it
          "brain_sent",  # the first model request left
          "first_token",  # the first piece of the reply came back
          "first_sentence",  # a whole sentence of the reply was read from the stream
          "reply",  # the model's whole reply was in
          "checked",  # the reply passed the checks and was handed to the mouth (a retry, when there is one, is before this)
          "tts_request",  # the mouth sent its request
          "tts_first_byte",  # the first audio came back
          "first_sound")  # the call's output started playing it to the client


class Turn:
    """The stamps of one turn of the user's. `steps` counts model steps, `early` says the first sentence went to the mouth
    before the reply was whole."""

    def __init__(self) -> None:
        self.at: dict[str, float] = {}
        self.steps = 0
        self.info: dict = {}
        self.logged = False

    def mark(self, stage: str, when: float) -> None:
        if stage in STAGES and not self.logged:
            self.at.setdefault(stage, when)

    def record(self) -> dict:
        """Milliseconds from the first stage that has a stamp (`t0`, wall time), in stage order; a stage that did not
        happen is left out."""
        known = [s for s in STAGES if s in self.at]
        if not known:
            return {}
        zero = self.at[known[0]]
        return {"from": known[0], "t0": round(zero, 3), **{s: int(round((self.at[s] - zero) * 1000)) for s in known[1:]},
                "steps": self.steps, **self.info}

    def line(self) -> str:
        self.logged = True
        return "turn timing: " + json.dumps(self.record(), separators=(",", ":"))
