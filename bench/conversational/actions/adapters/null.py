"""The floor: starts the session and does nothing with the user's speech."""

import time

from core.adapter import CAPABILITIES, Adapter


class NullAdapter(Adapter):
    name = "null"
    capabilities = CAPABILITIES  # every capability, each a no-op

    def say(self, pcm, rate, item):
        start = time.time()
        time.sleep(len(pcm) / rate)
        return start, time.time()
