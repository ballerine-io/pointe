"""One sound per session (pointe/tones.py, docs/features/session-tones.md): an optional short tone before a background
session's report, the same tone for a session every time, off unless turned on. Offline: no model, no network, no audio
device; the tones are measured as numbers.

Distinct is measured, not claimed: the distance between two tones is one minus the cosine likeness of their
third-octave spectra over time, and no two tones, and no tone and one of Pointe's other sounds, may be closer than
tones.MIN_DISTANCE. Whether people can name a session from its tone is a listening test that is still owed.
"""

import asyncio
import itertools
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
import thinking  # noqa: E402
import tones  # noqa: E402
from test_orchestrator import add, client_for, d, fake_conn  # noqa: E402,F401  (d is the daemon fixture)

RATE = 24000


def _other_sounds() -> dict:
    """Pointe's other sounds, as the daemon makes them: the waiting sound and the two chimes (daemon._tone)."""
    t = np.arange(int(RATE * 0.09)) / RATE
    fade = np.minimum(1, np.minimum(t, t[::-1]) * 60)

    def chime(notes):
        return np.concatenate([np.sin(2 * np.pi * f * t) * fade for f in notes]) * 0.25

    cue = np.frombuffer(thinking.cue_pcm(RATE), dtype=np.int16).astype(np.float64) / 32767
    return {"the waiting sound": cue, "the chime up": chime((520, 780)), "the chime down": chime((780, 520))}


# ---------- distinct, by measure ----------

def test_there_are_eight_tones_each_short_and_quiet():
    assert len(tones.PALETTE) == 8 and len({t.name for t in tones.PALETTE}) == 8
    for i in range(len(tones.PALETTE)):
        wave = tones.wave(i, RATE)
        assert 0.15 <= len(wave) / RATE <= tones.MAX_SECS, tones.PALETTE[i].name
        assert np.abs(wave).max() <= tones.LEVEL + 1e-9, "no louder than set"
        assert abs(wave[0]) < 1e-3 and abs(wave[-1]) < 1e-3, "starts and ends at zero: no click"
        pcm = np.frombuffer(tones.pcm(i, RATE), dtype=np.int16)
        assert len(pcm) == len(wave) and np.abs(pcm).max() <= tones.LEVEL * 32767 + 1


def test_no_two_tones_are_closer_than_the_threshold():
    pairs = {(a.name, b.name): tones.distance(tones.wave(i, RATE), tones.wave(j, RATE), RATE)
             for (i, a), (j, b) in itertools.combinations(enumerate(tones.PALETTE), 2)}
    assert len(pairs) == 28
    closest = min(pairs, key=pairs.get)
    assert pairs[closest] >= tones.MIN_DISTANCE, f"{closest} are {pairs[closest]:.2f} apart"
    assert tones.MIN_DISTANCE >= 0.5


def test_no_tone_is_close_to_another_sound_pointe_makes():
    for i, tone in enumerate(tones.PALETTE):
        for name, sound in _other_sounds().items():
            apart = tones.distance(tones.wave(i, RATE), sound, RATE)
            assert apart >= tones.MIN_DISTANCE, f"{tone.name} and {name} are {apart:.2f} apart"


def test_the_measure_itself_tells_same_from_different():
    a = tones.wave(0, RATE)
    assert tones.distance(a, a, RATE) < 1e-9
    assert tones.distance(a, a * 0.3, RATE) < 1e-9, "loudness is not what tells tones apart"
    semitone_up = tones.render([(hz * 2 ** (1 / 12), secs) for hz, secs in tones.PALETTE[0].notes], RATE)
    assert tones.distance(a, semitone_up, RATE) < tones.MIN_DISTANCE / 2, "a semitone apart is not distinct, and the measure says so"
    assert tones.distance(a, tones.wave(0, 16000), 24000, 16000) < 0.05, "the same tone at another rate is the same tone"


def test_the_doc_carries_the_measured_table():
    doc = (ROOT / "docs" / "features" / "session-tones.md").read_text()
    for line in tones.table(RATE).splitlines():
        assert line in doc, f"docs/features/session-tones.md: run `python3 -I pointe/tones.py` and paste its table: {line}"
    assert "listening test" in doc and "is still owed" in doc


# ---------- fixed per session ----------

def test_a_session_keeps_its_tone_and_sessions_on_the_voice_do_not_share_one():
    taken: dict[str, int] = {}
    for name in ["billing/main", "docs", "river-lantern", "harbor", "atlas", "shop", "api", "ingest"]:
        taken[name] = tones.assign(name, taken.values())
    assert sorted(taken.values()) == list(range(8)), "eight sessions, eight tones"
    assert tones.assign("billing/main", []) == tones.assign("billing/main", []), "the same name starts from the same tone"
    ninth = tones.assign("ninth", taken.values())
    assert 0 <= ninth < 8, "a ninth session shares one: there are eight"


# ---------- the daemon ----------

class Front:
    def __init__(self):
        self.frames = []

    async def push_frame(self, frame, direction=None):
        self.frames.append(frame)


def _finished(session, final: str) -> str:
    """A session ends its turn with `final`, as its harness's follower says it."""
    import harnesses
    from brief import FINAL_MARK
    from harnesses import finished_tag

    return f"{finished_tag(harnesses.get(session.harness).label)} {FINAL_MARK}{final}"


def _report(d, monkeypatch, on=True, mode="orchestrator", muted=False):
    """billing is active; docs, in the background, finishes a turn. Returns (docs, the audio frames pushed, what was fed)."""
    monkeypatch.setattr(d.PREFS, "values", {**d.PREFS.values, "reports.tones": on})
    add(d, "a", "billing/main")
    docs = add(d, "b", "docs")
    d.REGISTRY.set_active("a")
    d.REGISTRY.mode = mode
    d.state.conn = fake_conn()
    d.state.front = Front()
    monkeypatch.setattr(d, "_muted", lambda: muted)

    async def digest(session, text):
        return {"line": "Docs updated the changelog.", "say": "Docs updated the changelog.", "final": "Docs updated the changelog.",
                "excerpt": "Docs updated the changelog.", "speak": True, "urgency": "normal", "waiting": False}
    monkeypatch.setattr(d, "_digest_turn", digest)
    monkeypatch.setattr(d, "_quick_report", lambda *a, **k: None)
    monkeypatch.setattr(d, "_quick_answer", lambda *a, **k: None)

    async def night(*a, **k):
        pass
    monkeypatch.setattr(d, "_night_report", night)
    asyncio.run(d.feed(docs, _finished(docs, "Docs updated the changelog."), True))
    return docs, d.state.front.frames, d.state.conn.injector.fed


def test_off_by_default_and_then_no_sound(d, monkeypatch):
    import prefs

    assert prefs.SCHEMA["reports.tones"] == (False, bool)
    docs, frames, fed = _report(d, monkeypatch, on=False)
    assert frames == [] and fed, "the report is told, with no tone"
    assert docs.tone is None


def test_on_a_background_sessions_report_starts_with_its_tone(d, monkeypatch):
    docs, frames, fed = _report(d, monkeypatch)
    assert len(frames) == 1 and fed
    assert frames[0].audio == tones.pcm(docs.tone, frames[0].sample_rate)
    assert docs.tone == tones.assign("docs", [])


def test_the_same_session_sounds_the_same_every_time_and_another_differs(d, monkeypatch):
    docs, frames, _ = _report(d, monkeypatch)
    first = frames[0].audio
    harbor = add(d, "c", "harbor")
    asyncio.run(d.feed(docs, _finished(docs, "Docs fixed the link."), True))
    asyncio.run(d.feed(harbor, _finished(harbor, "Harbor rebased."), True))
    assert frames[1].audio == first and frames[2].audio != first
    assert harbor.tone != docs.tone


def test_the_session_you_are_talking_to_and_a_muted_pointe_get_no_tone(d, monkeypatch):
    docs, frames, _ = _report(d, monkeypatch, muted=True)
    assert frames == [], "muted: nothing is sounded"


def test_the_active_sessions_own_report_gets_no_tone(d, monkeypatch):
    docs, frames, _ = _report(d, monkeypatch)
    billing = next(s for s in d.REGISTRY.sessions.values() if s.name == "billing/main")
    before = len(frames)
    asyncio.run(d.feed(billing, _finished(billing, "Billing ran the tests."), True))
    assert len(frames) == before, "its words are the answer you are waiting for: no tone"


def test_the_tone_is_kept_with_the_session_and_shown_in_the_status(d, monkeypatch):
    docs, frames, _ = _report(d, monkeypatch)
    row = next(s for s in client_for(d).get("/voice/status").json()["sessions"] if s["name"] == "docs")
    assert row["tone"] == {"index": docs.tone, "name": tones.PALETTE[docs.tone].name}
    import sessions

    assert "tone" in sessions.PERSISTED, "a restart of the daemon does not change a session's tone"


def test_the_setting_round_trips(d, monkeypatch):
    monkeypatch.setattr(d.PREFS, "values", dict(d.PREFS.values))
    c = client_for(d)
    assert c.get("/voice/prefs").json()["reports.tones"] is False
    assert c.post("/voice/prefs", json={"reports.tones": True}).status_code == 200
    assert c.get("/voice/prefs").json()["reports.tones"] is True


def test_with_the_setting_off_the_status_names_no_tone(d, monkeypatch):
    docs, _, _ = _report(d, monkeypatch)
    monkeypatch.setattr(d.PREFS, "values", {**d.PREFS.values, "reports.tones": False})
    row = next(s for s in client_for(d).get("/voice/status").json()["sessions"] if s["name"] == "docs")
    assert row["tone"] is None and docs.tone is not None, "kept for when it is turned on again; not shown meanwhile"


def test_the_words_are_the_same_on_the_page_and_in_the_apps():
    page = (ROOT / "pointe" / "ui_tones.html").read_text()
    swift = (ROOT / "apps" / "PointeKit" / "Sources" / "PointeUI" / "Tones.swift").read_text()
    assert tones.COPY["setting"] in page and tones.COPY["setting"] in swift
    assert tones.COPY["hint"] in page and tones.COPY["hint"] in swift
    assert "`tone: ${name}`" in page and '"tone: \\(name)"' in swift and tones.COPY["row"] == "tone: {name}"
