"""What the two spoken baselines share: the same audio, heard by Pointe's default recognizer, then a routing policy
that types into the chosen session's pty. Their speech out is not rendered: this benchmark scores only where requests
go and whether the arm asked, which is read from the arm's own text for every arm."""

import time

from ..core import corpus, ears, ledger
from ..core.adapter import AgentArm


class SpokenArm(AgentArm):
    kind = "audio"
    capabilities = frozenset({"audio_in", "text_in", "sessions"})

    async def start(self, conv_id, repos):
        await super().start(conv_id, repos)
        self.soniox_seconds = 0.0
        self.heard: list[dict] = []

    async def utter(self, clip_id: str, pcm48):
        start = time.time()
        text, seconds, cached = await ears.transcribe(clip_id, corpus.to_16k(pcm48), self.terms())
        if not cached:
            self.soniox_seconds += seconds
        end = time.time()
        self.heard.append({"clip": clip_id, "text": text, "cached": cached})
        self.emit("heard", text=text, clip=clip_id)
        await self.handle(text)
        return start, end

    def terms(self) -> list[str]:
        return [n.replace("-", " ") for n in self.repos]

    async def handle(self, transcript: str) -> None:
        raise NotImplementedError

    def spend(self):
        rows = super().spend()
        if self.soniox_seconds:
            rows.append({"vendor": "soniox", "what": "ears", "model": ears.model(), "how": "computed",
                         "usd": round(self.soniox_seconds / 3600 * ledger.PRICES["soniox_stream_hour"], 6),
                         "seconds": round(self.soniox_seconds, 1)})
        return rows
