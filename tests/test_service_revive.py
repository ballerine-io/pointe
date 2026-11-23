"""Ears or a voice that gave up reconnecting come back once their vendor answers again, and the line says what really
happened. QA round 2: after a 2-second blip Pipecat spent its 3 retries in 17 ms and the ears stayed deaf for the rest of
the call; a refused key and an HTTP 500 were both called "the connection dropped"; raw Pipecat errors with a local path
stayed on the page for 90 s and went to paired phones."""

import asyncio
from types import SimpleNamespace

import pytest
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService

from test_orchestrator import d  # noqa: F401


class Ears(STTService):
    """Ears whose link comes back after `fails` tries."""
    is_usable = property(lambda self: self._usable)

    @classmethod
    def make(cls, fails: int) -> "Ears":
        ears = cls.__new__(cls)
        ears._name, ears._usable, ears.fails, ears.tries = "GeminiSTTService#0", False, fails, 0
        return ears

    async def set_usable(self, value):
        self._usable = value

    async def _do_reconnect(self):
        self.tries += 1
        if self.tries <= self.fails:
            raise ConnectionError("cannot connect")

    async def run_stt(self, audio):
        yield None


@pytest.fixture
def quick(d, monkeypatch):
    said = []

    async def say_exactly(line, tag):
        said.append(line)

    monkeypatch.setattr(d, "_say_exactly", say_exactly)
    monkeypatch.setattr(d, "_problem", (0.0, ""))
    monkeypatch.setattr(d, "_fault", (0.0, "", ""))
    monkeypatch.setattr(d, "LOST_SETTLE_SECS", 0.0)
    monkeypatch.setattr(d, "REVIVE_WAITS", (0.01,))
    monkeypatch.setattr(d, "REVIVE_SETTLE_SECS", 0.01)
    monkeypatch.setattr(d, "_setup", d.vendors.Setup(brain="gemini:b", reader="gemini:r", checker="gemini:c",
                                                     ears="gemini:e", mouth="gemini:m"))
    monkeypatch.setattr(d.state, "conn", SimpleNamespace())
    monkeypatch.setattr(d.state, "lost", None)
    return said


def note(d, text, name="daemon"):
    d._note_problem(SimpleNamespace(record={"message": text, "name": name}))


def test_ears_that_gave_up_come_back_when_the_link_does_and_say_so(d, quick):
    ears = Ears.make(fails=2)

    async def call():
        await d._service_lost(ears)
        assert d.vendor_fault() == {"vendor": "gemini", "ears": True, "kind": "lost"}
        for _ in range(200):
            if d.state.lost is None:
                break
            await asyncio.sleep(0.01)

    asyncio.run(call())
    assert ears.tries == 3 and ears.is_usable
    assert d.state.lost is None and d.vendor_fault() is None and d.current_problem() is None
    assert quick == ["I can't hear you: the connection to Gemini dropped. I'm reconnecting; typing still works.",
                     "I can hear you again."]


def test_a_new_call_stops_the_tries_for_the_old_one(d, quick):
    ears = Ears.make(fails=1000)

    async def call():
        await d._service_lost(ears)
        await asyncio.sleep(0.05)
        d.state.conn = SimpleNamespace()  # hung up, called again
        tries = ears.tries
        await asyncio.sleep(0.1)
        return tries

    tries = asyncio.run(call())
    assert ears.tries <= tries + 1


def test_a_refused_key_is_never_called_a_dropped_connection_and_is_not_retried(d, quick):
    note(d, "GeminiSTTService#0 error: 400 API key not valid. Please pass a valid API key.")
    ears = Ears.make(fails=0)
    asyncio.run(d._service_lost(ears))
    assert quick == [] and d.state.lost is None and ears.tries == 0
    assert "refused" in d.current_problem() and "dropped" not in d.current_problem()


def test_a_server_error_is_called_a_server_error(d, quick):
    note(d, "GeminiSTTService#0 error: 500 INTERNAL. Internal error encountered.")
    ears = Ears.make(fails=1000)
    asyncio.run(d._service_lost(ears))
    assert quick and "dropped" not in quick[0] and "not answering (an error on its side)" in quick[0]
    assert d.vendor_fault()["kind"] == "down"


def test_a_library_error_is_never_shown_word_for_word(d, quick):
    note(d, "SonioxTTSService#0 exception (/Users/someone/.claude/plugins/pointe/.venv/lib/python3.12/site-packages/"
            "pipecat/services/websocket_service.py:260): reconnection attempt 1 failed", name="pipecat.services.soniox.tts")
    note(d, "voice: GeminiSTTService#0 can no longer do its job", name="pipecat.pipeline.worker")
    assert d.current_problem() is None
    note(d, "GeminiSTTService#0 error: 429 RESOURCE_EXHAUSTED quota", name="pipecat.services.google.stt")
    assert "quota" in d.current_problem() and "Service#" not in d.current_problem()  # still put in words


def test_a_websocket_that_did_not_open_is_not_called_back(d, quick):
    ears = Ears.make(fails=0)
    checks = iter([False, False, True])

    async def verify():
        return next(checks)
    ears._verify_connection = verify

    async def call():
        await d._service_lost(ears)
        for _ in range(200):
            if d.state.lost is None:
                break
            await asyncio.sleep(0.01)

    asyncio.run(call())
    assert ears.tries == 3 and quick[-1] == "I can hear you again." and len(quick) == 2


class Voice(TTSService):
    """A websocket voice whose socket did not open, and opens after `fails` tries."""
    is_usable = property(lambda self: self._usable)

    @classmethod
    def make(cls, fails: int) -> "Voice":
        voice = cls.__new__(cls)
        voice._name, voice._usable, voice.fails, voice.tries = "GeminiTTSService#0", False, fails, 0
        return voice

    async def set_usable(self, value):
        self._usable = value

    async def _reconnect_websocket(self, attempt):
        self.tries += 1
        if self.tries <= self.fails:
            raise TimeoutError("timed out during opening handshake")

    async def run_tts(self, text, *args, **kwargs):
        yield None


def test_one_failed_voice_handshake_is_tried_again_and_the_page_shows_words(d, quick):
    """Final review, round 5, Free start under load: Gemini's speech socket timed out on open, Pipecat gave up at once,
    nothing was tried again, and the page showed "GeminiTTSService#0 error: TTS context <uuid> completed with no audio"."""
    note(d, "GeminiTTSService#0 error: TTS context 5b0e2c4a-7d1f-4c3e-9a8b-2f6d1e0c9b7a completed with no audio",
         name="pipecat.services.google.tts")
    note(d, "voice: GeminiTTSService#0 can no longer do its job", name="pipecat.pipeline.worker")
    voice = Voice.make(fails=2)

    async def call():
        await d._service_lost(voice)
        shown = d.current_problem()
        for _ in range(300):
            if d.state.lost is None:
                break
            await asyncio.sleep(0.01)
        return shown

    shown = asyncio.run(call())
    assert shown and shown.startswith("The voice stopped") and "Service#" not in shown and "TTS context" not in shown, shown
    assert voice.tries == 3 and voice.is_usable
    assert d.state.lost is None and d.current_problem() is None


def test_the_waits_between_tries_grow():
    import daemon
    waits = list(daemon.REVIVE_WAITS)
    assert len(waits) > 1 and waits == sorted(waits) and waits[0] < waits[-1]
