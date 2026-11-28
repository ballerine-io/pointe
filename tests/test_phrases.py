"""Short lines kept as audio (pointe/phrases.py): a repeat is played from memory, never stale, never a cut line."""

import asyncio
import sys
from pathlib import Path
from collections import OrderedDict

from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame, TTSSpeakFrame
from pipecat.services.tts_service import TTSService

import phrases

sys.path.insert(0, str(Path(__file__).parent))
from test_orchestrator import d  # noqa: E402,F401  (the daemon fixture)


class FakeMouth(TTSService):
    """Says each line as two chunks of audio that encode the line and the speed, and counts what it was asked."""

    def __init__(self, fail_on: str = ""):
        super().__init__(sample_rate=24000)
        self.asked: list[str] = []
        self.fail_on = fail_on
        self.stamped: list[str] = []

    async def run_tts(self, text: str, context_id: str):
        self.asked.append(text)
        body = f"{text}|{self._settings.voice}".encode()
        yield TTSAudioRawFrame(body + b"-1", self.sample_rate, 1, context_id=context_id)
        await self.add_word_timestamps([(w, 0.1 * i) for i, w in enumerate(text.split())], context_id)
        if text == self.fail_on:
            yield ErrorFrame(error="vendor failed")
        yield TTSAudioRawFrame(body + b"-2", self.sample_rate, 1, context_id=context_id)

    async def add_word_timestamps(self, word_times, context_id=None, *args, **kwargs):
        self.stamped += [w for w, _ in word_times]


async def _say(mouth, text: str, context_id: str = "c1") -> list:
    return [f async for f in mouth.run_tts(text, context_id)]


def _audio(frames) -> list[bytes]:
    return [f.audio for f in frames if isinstance(f, TTSAudioRawFrame)]


def test_a_repeated_short_line_is_played_from_memory_with_the_same_audio():
    mouth = FakeMouth()
    kept = phrases.Phrases(mouth, store=OrderedDict())
    first = asyncio.run(_say(mouth, "Sent to billing.", "c1"))
    again = asyncio.run(_say(mouth, "Sent to billing.", "c2"))
    assert mouth.asked == ["Sent to billing."]
    assert _audio(again) == _audio(first) and len(_audio(again)) == 2
    assert all(f.context_id == "c2" for f in again)
    assert (kept.hits, kept.misses) == (1, 1)


def test_the_next_call_with_a_new_mouth_of_the_same_voice_finds_the_line():
    store = OrderedDict()
    first_call, next_call = FakeMouth(), FakeMouth()
    phrases.Phrases(first_call, store=store)
    asyncio.run(_say(first_call, "Asking quarry."))
    phrases.Phrases(next_call, store=store)
    asyncio.run(_say(next_call, "Asking quarry."))
    assert (first_call.asked, next_call.asked) == (["Asking quarry."], [])


def test_another_speed_or_voice_is_a_new_line_not_a_stale_one():
    mouth = FakeMouth()
    phrases.Phrases(mouth, store=OrderedDict())
    asyncio.run(_say(mouth, "Asking quarry."))
    mouth._settings.voice = "another"  # what a settings update frame changes, as a speed change does
    after = asyncio.run(_say(mouth, "Asking quarry."))
    assert mouth.asked == ["Asking quarry.", "Asking quarry."]
    assert _audio(after)[0].startswith(b"Asking quarry.|another")


def test_a_long_line_is_never_kept():
    mouth = FakeMouth()
    phrases.Phrases(mouth, store=OrderedDict())
    line = "The billing tests failed in three places this morning."
    asyncio.run(_say(mouth, line))
    asyncio.run(_say(mouth, line))
    assert mouth.asked == [line, line]


def test_a_line_with_an_error_is_not_kept():
    mouth = FakeMouth(fail_on="Approved.")
    phrases.Phrases(mouth, store=OrderedDict())
    asyncio.run(_say(mouth, "Approved."))
    asyncio.run(_say(mouth, "Approved."))
    assert mouth.asked == ["Approved.", "Approved."]


def test_a_line_cut_off_while_it_was_made_is_not_kept():
    mouth = FakeMouth()
    phrases.Phrases(mouth, store=OrderedDict())

    async def cut():
        gen = mouth.run_tts("Sent to atlas.", "c1")
        await gen.__anext__()  # the first chunk, then the barge-in drops the rest
        await gen.aclose()

    asyncio.run(cut())
    asyncio.run(_say(mouth, "Sent to atlas."))
    assert mouth.asked == ["Sent to atlas.", "Sent to atlas."]


def test_warming_makes_each_line_once_and_sends_nothing_to_the_call():
    mouth = FakeMouth()
    mouth._previous_text = "Earlier words."
    kept = phrases.Phrases(mouth, store=OrderedDict())
    made = asyncio.run(kept.warm(["Sent to billing.", "Asking billing.", "Sent to billing.", ""]))
    assert made == 2 and mouth.asked == ["Sent to billing.", "Asking billing."]
    assert mouth.stamped == []  # a warm-up's word timings reach no one
    assert mouth._previous_text == "Earlier words."  # the next real line is asked what it would have been
    asyncio.run(_say(mouth, "Asking billing."))
    assert mouth.asked == ["Sent to billing.", "Asking billing."]
    assert asyncio.run(kept.warm(["Asking billing."])) == 0


def test_a_spoken_line_keeps_its_word_timings():
    mouth = FakeMouth()
    phrases.Phrases(mouth, store=OrderedDict())
    asyncio.run(_say(mouth, "Sent to billing."))
    assert mouth.stamped == ["Sent", "to", "billing."]


def test_the_oldest_line_goes_when_memory_is_full(monkeypatch):
    monkeypatch.setattr(phrases, "MAX_ITEMS", 2)
    mouth = FakeMouth()
    phrases.Phrases(mouth, store=OrderedDict())
    for line in ("One.", "Two.", "One.", "Three.", "One.", "Two."):
        asyncio.run(_say(mouth, line))
    assert mouth.asked == ["One.", "Two.", "Three.", "Two."]


def test_through_a_pipeline_the_second_line_comes_without_asking_the_vendor():
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.tests.utils import run_test

    mouth = FakeMouth()
    phrases.Phrases(mouth, store=OrderedDict())
    down, _ = asyncio.run(run_test(Pipeline([mouth]),
                                   frames_to_send=[TTSSpeakFrame("Sent to billing."), TTSSpeakFrame("Sent to billing.")]))
    assert mouth.asked == ["Sent to billing."]
    audio = [f.audio for f in down if isinstance(f, TTSAudioRawFrame)]
    assert audio.count(b"Sent to billing.|NOT_GIVEN-1") == 2


def test_the_warmed_lines_are_the_acknowledgements_the_daemon_says(d):  # noqa: F811
    """What _quick_ack says for a plain send or question to each session on the call, and an approval's answer, is
    warmed: a line warmed in other words would never be a hit."""
    from test_orchestrator import add

    add(d, "s1", "billing/main")
    add(d, "s2", "tariff-web/main")
    lines = d._ack_lines()
    for name in ("billing/main", "tariff-web/main"):
        sent = {"sent_to": [name], "routing": "brain"}
        assert d._quick_ack({"message": "Bump the version."}, sent, "Bump the version.") in lines
        assert d._quick_ack({"message": "Did it pass?"}, sent, "Did it pass?") in lines
    assert d.ANSWERED_LINES[("allow", False)] in lines and d.ANSWERED_LINES[("deny", False)] in lines
    assert all(phrases.MAX_WORDS >= len(line.split()) for line in lines)


def test_the_warm_up_runs_for_the_call_once_per_mouth_and_stops_with_it(d, monkeypatch):  # noqa: F811
    from test_orchestrator import add

    add(d, "s1", "billing/main")
    mouth = FakeMouth()
    kept = phrases.Phrases(mouth, store=OrderedDict())
    monkeypatch.setattr(d, "PHRASES_WARM_SECS", 0.01)
    monkeypatch.setattr(d.state, "phrases", kept)
    monkeypatch.setattr(d.state, "conn", object())

    async def call():
        loops = [asyncio.create_task(d._warm_phrases(kept)) for _ in range(2)]  # a resumed link connects again
        await asyncio.sleep(0.05)
        d.state.conn = None
        await asyncio.wait_for(asyncio.gather(*loops), 1)

    asyncio.run(call())
    assert sorted(mouth.asked) == sorted(d._ack_lines())  # each once, though two loops were asked for


def test_the_daemon_wraps_the_brain_fronts_mouth_where_it_is_built(d):  # noqa: F811
    import inspect

    source = inspect.getsource(d)
    assert "state.phrases = phrases.Phrases(mouth)" in source
    assert "asyncio.create_task(_warm_phrases(state.phrases))" in source
