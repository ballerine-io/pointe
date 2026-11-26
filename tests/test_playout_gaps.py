"""The bot's voice does not break between words on a jittery path (tests/playout_sim.py, a fake clock).

Pipecat's transport paces the voice at the speed it plays. Sent so, a listener holds only what its own buffer waited for
at the start (before 0.10.1 the apps 100 ms, the page nothing), and each late chunk on a TCP path, a lost segment's retransmission above
all, is a gap in the middle of a word. The daemon sends the first phone.SEND_LEAD_SECS of each reply at once and paces
the rest, so every client holds that much from the start.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import playout_sim as sim
import pytest

import phone

ROOT = Path(__file__).resolve().parents[1]


def test_a_reply_starts_with_the_lead_in_hand_and_then_goes_at_the_voices_pace():
    times = sim.send_times(10.0, start=0.0, lead=phone.SEND_LEAD_SECS)
    lead_chunks = round(phone.SEND_LEAD_SECS / sim.CHUNK)
    assert times[lead_chunks] < 0.5, "the first half second goes as fast as the voice service makes it"
    tail = times[-1] - times[lead_chunks]
    assert abs(tail - (len(times) - 1 - lead_chunks) * sim.CHUNK) < 0.05, "and the rest at the voice's own pace"


def test_the_lead_is_bounded_and_comes_back_after_a_pause():
    clock, start, sent = 0.0, 1000.0, 0.0  # pipecat's clock starts at 0, far behind time.monotonic()
    now = start
    for _ in range(500):  # a long reply the voice service made at once: each chunk goes as soon as the clock allows
        sent += 0.04
        clock = phone.next_send_at(clock, now, chunk_secs=0.04)
        assert sent - (now - start) <= phone.SEND_LEAD_SECS + 0.04 + 1e-9, "never further ahead than the lead"
        now = max(now, clock)  # send_ahead sleeps until the clock allows the next chunk
    assert abs(sent - (now - start) - phone.SEND_LEAD_SECS) < 1e-6, "and that far ahead all along a long reply"
    assert phone.next_send_at(clock, now=now + 60, chunk_secs=0.04) == now + 60 - phone.SEND_LEAD_SECS + 0.04, \
        "a reply after a pause starts with the whole lead"


SEEDS = range(1, 6)


def heard(client: str, profile: str, lead: float, before: bool = False) -> sim.Result:
    return sim.mean([sim.listen(client, profile, lead, seed, before) for seed in SEEDS])


def test_on_a_jittery_lossy_path_the_voice_has_next_to_no_gaps():
    """docs/phone.md, "The voice plays smoothly", quotes these numbers."""
    before = {c: heard(c, "relay", sim.CHUNK, before=True) for c in ("page", "app")}  # 0.10.0's daemon, page and apps
    after = {c: heard(c, "relay", phone.SEND_LEAD_SECS) for c in ("page", "app")}
    print("before", before, "after", after)
    for client in ("page", "app"):
        assert after[client].gaps_per_min <= 0.4 and after[client].gap_ms_per_min <= 30, (client, after)
        assert before[client].gaps_per_min >= 4 * after[client].gaps_per_min, (client, before, after)
    assert after["app"].first_sound_ms <= before["app"].first_sound_ms, "and the apps' voice starts sooner, not later"
    assert after["page"].first_sound_ms <= before["page"].first_sound_ms + 120, "the page's waits for its hold, briefly"


def test_on_a_clean_path_nothing_changes_but_the_page_stops_clicking():
    for client in ("page", "app"):
        r = sim.listen(client, "lan", lead=phone.SEND_LEAD_SECS)
        assert r.gaps_per_min == 0, (client, r)


def test_the_apps_jitter_buffer_mirror_agrees_with_linkpolicy_swift():
    swift = (ROOT / "apps/PointeKit/Sources/PointeKit/LinkPolicy.swift").read_text()
    for name, value in (("minTarget", sim.JitterBuffer.MIN_TARGET), ("maxTarget", sim.JitterBuffer.MAX_TARGET),
                        ("startTarget", sim.JitterBuffer.START_TARGET), ("sameReply", sim.JitterBuffer.SAME_REPLY),
                        ("calm", sim.JitterBuffer.CALM)):
        found = re.search(rf"static let {name}: TimeInterval = ([0-9.]+)", swift)
        assert found and float(found.group(1)) == value, name
    assert "target * 1.5 + 0.02" in swift and "target - 0.02" in swift


def test_the_page_worklet_itself_hears_what_the_page_listener_does(tmp_path):
    """pointe/ui.html's own `player` worklet, run in node on the same arrivals (tests/page_player.js)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on this machine: CI's runners have it")
    worklet = re.search(r"const CAPTURE = `(.*?)`;", (ROOT / "pointe/ui.html").read_text(), re.S).group(1)
    (tmp_path / "worklet.js").write_text(worklet)
    talk, arrived = sim.arrivals("relay", phone.SEND_LEAD_SECS, seed=1)
    (tmp_path / "arrivals.json").write_text(json.dumps(arrived))
    out = subprocess.run([node, str(ROOT / "tests/page_player.js"), str(tmp_path / "worklet.js"), str(tmp_path / "arrivals.json")],
                         capture_output=True, text=True, timeout=120, check=True)
    got = json.loads(out.stdout)
    page = sim.result(talk, got["gaps"], got["gap_secs"], dict(enumerate(got["first"])))
    mirror = sim.listen("page", "relay", phone.SEND_LEAD_SECS, seed=1)
    print("worklet", page, "mirror", mirror)
    assert abs(page.gaps_per_min - mirror.gaps_per_min) <= 0.15 and abs(page.gap_ms_per_min - mirror.gap_ms_per_min) <= 25, (page, mirror)
    assert page.gaps_per_min <= 0.3 and page.gap_ms_per_min <= 30, page


def test_the_echo_guard_hears_the_voice_stop_as_late_as_the_lead_makes_it():
    import echo

    assert echo.PLAYBACK_LAG_SECS == 0.3 + phone.SEND_LEAD_SECS
    assert echo.AUDIO_TAIL_SECS >= echo.PLAYBACK_LAG_SECS
