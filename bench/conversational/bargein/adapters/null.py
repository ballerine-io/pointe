"""Starts the session and does nothing: the floor. Every input is dropped."""

from core.adapter import now
from adapters.base import PtyArm


class Null(PtyArm):
    name = "null"
    capabilities = frozenset({"audio_in", "text_in", "speech_out", "approvals", "sessions", "interrupt"})

    def say(self, pcm, rate):
        t = now()
        return t, t + len(pcm) / rate

    def type(self, text, session=None):
        return now()

    def key(self, name, session=None):
        return now()
