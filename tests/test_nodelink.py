"""The hub-node link: frames, the nonce challenge, the heartbeat, and transcript shipping (docs/design/multi-machine.md)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nodelink  # noqa: E402
from nodelink import HUB_FRAMES, NODE_FRAMES, decode, encode  # noqa: E402

KEY = "ab" * 32
HUB_ID = "hub-1"


def _hello(**over):
    frame = {"protocol": 1, "auth": "00", "now": 1731590520.5,
             "node": {"id": "n1", "name": "devbox", "os": "linux", "arch": "x86_64", "version": "1.0.1",
                      "harnesses": ["claude-code"]}}
    return {**frame, **over}


def test_a_frame_round_trips():
    text = encode("send", req="r1", id="s1", text="pull")
    assert json.loads(text) == {"t": "send", "req": "r1", "id": "s1", "text": "pull"}
    assert decode(text, HUB_FRAMES) == {"t": "send", "req": "r1", "id": "s1", "text": "pull"}


def test_unknown_types_are_ignored_both_ways():
    assert decode(json.dumps({"t": "from-the-future", "x": 1}), NODE_FRAMES) is None
    assert decode(json.dumps({"t": "from-the-future", "x": 1}), HUB_FRAMES) is None


def test_a_frame_is_only_accepted_in_its_own_direction():
    text = encode("send", req="r1", id="s1", text="pull")  # hub to node
    assert decode(text, NODE_FRAMES) is None


@pytest.mark.parametrize("text", ["", "not json", "[1, 2]", '"send"', '{"no": "type"}', '{"t": 7}'])
def test_garbage_is_dropped(text):
    assert decode(text, NODE_FRAMES) is None


def test_extra_fields_are_kept_so_one_side_can_move_first():
    frame = decode(json.dumps({"t": "send.result", "req": "r1", "ok": True, "later": "field"}), NODE_FRAMES)
    assert frame == {"t": "send.result", "req": "r1", "ok": True, "later": "field"}


@pytest.mark.parametrize("frame", [
    {"t": "send.result", "req": "r1"},  # missing ok
    {"t": "send.result", "req": "r1", "ok": "yes"},  # a string is not a bool
    {"t": "pong", "id": True},  # a bool is not an int
    {"t": "session.left", "id": "s1", "why": "bored"},
    {"t": "permission.resolved", "id": "s1", "request_id": "p1", "how": "voice"},
    {"t": "transcript", "id": "s1", "gen": 0, "offset": 10, "next_offset": 5, "entries": []},
    {"t": "transcript", "id": "s1", "gen": 0, "offset": -1, "next_offset": 5, "entries": []},
    {"t": "transcript", "id": "s1", "gen": 0, "offset": 0, "next_offset": 5, "entries": ["no newline"]},
    {"t": "files", "id": "s1", "names": [f"f{i}" for i in range(41)]},
    {"t": "hello", **_hello(node={"id": "n1"})},
])
def test_a_malformed_node_frame_is_dropped(frame):
    assert decode(json.dumps(frame), NODE_FRAMES) is None


@pytest.mark.parametrize("frame", [
    {"t": "permission.answer", "id": "s1", "request_id": "p1", "verdict": "maybe", "how": "voice"},
    {"t": "permission.answer", "id": "s1", "request_id": "p1", "verdict": "allow", "how": "telepathy"},
    {"t": "permission.answer", "id": "s1", "request_id": "p1", "verdict": "allow", "how": "voice", "spoken": 3},
    {"t": "call", "up": True},
    {"t": "welcome", "protocol": 1, "call_up": False, "approvals_terminal": False, "vendors": [],
     "resume": {"s1": {"gen": 0}}},
])
def test_a_malformed_hub_frame_is_dropped(frame):
    assert decode(json.dumps(frame), HUB_FRAMES) is None


def test_optional_fields_may_be_absent_or_present():
    assert decode(encode("permission.answered", request_id="p1", ok=True), NODE_FRAMES)
    assert decode(encode("permission.answered", request_id="p1", ok=False, why="stale"), NODE_FRAMES)
    assert decode(encode("ping", id=1, rtt_ms=None), HUB_FRAMES)
    assert decode(encode("unpaired"), HUB_FRAMES) == {"t": "unpaired"}
    assert decode(encode("hello", **_hello()), NODE_FRAMES)


def test_encode_refuses_what_decode_would_drop():
    with pytest.raises(ValueError):
        encode("send.result", req="r1")
    with pytest.raises(ValueError):
        encode("no-such-frame")


def test_a_frame_over_the_cap_is_refused():
    big = "x" * nodelink.MAX_FRAME_BYTES
    assert decode(json.dumps({"t": "send", "req": "r", "id": "s", "text": big}), HUB_FRAMES) is None
    with pytest.raises(ValueError):
        encode("send", req="r", id="s", text=big)


def test_an_entry_over_the_cap_is_dropped_and_the_frame_kept():
    huge = "x" * nodelink.MAX_ENTRY_BYTES + "\n"
    frame = decode(json.dumps({"t": "transcript", "id": "s1", "gen": 0, "offset": 0, "next_offset": 9999999,
                               "entries": ['{"a":1}\n', huge, '{"b":2}\n']}), NODE_FRAMES)
    assert frame["entries"] == ['{"a":1}\n', '{"b":2}\n'] and frame["next_offset"] == 9999999


def test_the_nonce_challenge_accepts_only_the_right_key():
    nonce = nodelink.new_nonce()
    assert len(bytes.fromhex(nonce)) == 32
    auth = nodelink.answer(KEY, nonce, HUB_ID)
    assert nodelink.check(KEY, nonce, HUB_ID, auth)
    assert not nodelink.check("cd" * 32, nonce, HUB_ID, auth)
    assert not nodelink.check(KEY, nonce, "another-hub", auth)  # an answer for one hub is no good to another


def test_a_replayed_hello_fails_on_a_new_connection():
    first, second = nodelink.new_nonce(), nodelink.new_nonce()
    assert first != second
    replayed = nodelink.answer(KEY, first, HUB_ID)
    assert not nodelink.check(KEY, second, HUB_ID, replayed)


@pytest.mark.parametrize("offered", ["", "zz", "00" * 32, None, 5])
def test_a_bad_answer_is_refused_without_raising(offered):
    assert not nodelink.check(KEY, nodelink.new_nonce(), HUB_ID, offered)


def test_keys_are_256_bits_and_fingerprints_are_16_hex():
    key = nodelink.new_key()
    assert len(bytes.fromhex(key)) == 32 and key != nodelink.new_key()
    fp = nodelink.fingerprint(key)
    assert len(fp) == 16 and int(fp, 16) >= 0 and fp == nodelink.fingerprint(key)


def test_one_live_connection_per_key():
    links = nodelink.Links()
    first, second = object(), object()
    assert links.claim("n1", first)
    assert not links.claim("n1", second)  # closed with CLOSE_ALREADY_CONNECTED; the first stays
    links.release("n1", second)  # the refused one closing must not free the slot
    assert not links.claim("n1", object())
    links.release("n1", first)
    assert links.claim("n1", second)
    assert links.claim("n2", first)


def test_close_codes_match_the_contract():
    assert (nodelink.CLOSE_BAD_HELLO, nodelink.CLOSE_UNAUTHORIZED, nodelink.CLOSE_DEAD,
            nodelink.CLOSE_ALREADY_CONNECTED, nodelink.CLOSE_TOO_OLD) == (4400, 4401, 4408, 4409, 4426)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_heartbeat_dies_after_12_s_without_a_pong():
    clock = Clock()
    beat = nodelink.Heartbeat(clock)
    ping = decode(beat.ping(), HUB_FRAMES)
    assert ping["t"] == "ping" and ping["rtt_ms"] is None
    clock.now += 0.05
    beat.pong(ping["id"])
    assert beat.rtt_ms == 50 and not beat.dead()
    clock.now += 11.9
    assert not beat.dead()
    clock.now += 0.2
    assert beat.dead()


def test_a_node_that_never_answers_is_dead_too():
    """Unlike the phone, there is no old node that predates pongs: silence from the start is a dead link."""
    clock = Clock()
    beat = nodelink.Heartbeat(clock)
    beat.ping()
    clock.now += nodelink.DEAD_AFTER_SECS + 0.1
    assert beat.dead()


def test_an_unknown_pong_does_not_set_a_round_trip():
    clock = Clock()
    beat = nodelink.Heartbeat(clock)
    beat.pong(99)
    assert beat.rtt_ms is None and not beat.dead()


def test_reconnect_backoff_doubles_to_30_s():
    assert [nodelink.backoff(n) for n in range(7)] == [1, 2, 4, 8, 16, 30, 30]


def test_only_complete_lines_are_shipped():
    data = b'{"a":1}\n{"b":2}\n{"c":'
    frames, next_offset = nodelink.transcript_frames("s1", 0, 100, data)
    assert next_offset == 100 + len(b'{"a":1}\n{"b":2}\n')  # the partial tail waits for the next poll
    [frame] = [decode(f, NODE_FRAMES) for f in frames]
    assert frame["offset"] == 100 and frame["next_offset"] == next_offset
    assert frame["entries"] == ['{"a":1}\n', '{"b":2}\n']


def test_nothing_complete_ships_nothing():
    assert nodelink.transcript_frames("s1", 0, 7, b'{"partial"') == ([], 7)


def test_offsets_count_bytes_not_characters():
    line = '{"text":"שלום"}\n'
    frames, next_offset = nodelink.transcript_frames("s1", 0, 0, line.encode())
    assert next_offset == len(line.encode()) > len(line)


def test_a_large_read_splits_into_frames_under_the_cap_with_contiguous_offsets():
    line = b'{"x":"' + b"y" * 200_000 + b'"}\n'
    data = line * 12
    frames, next_offset = nodelink.transcript_frames("s1", 3, 0, data)
    decoded = [decode(f, NODE_FRAMES) for f in frames]
    assert len(frames) > 1 and all(len(f.encode()) <= nodelink.MAX_FRAME_BYTES for f in frames)
    assert decoded[0]["offset"] == 0 and decoded[-1]["next_offset"] == next_offset == len(data)
    assert all(a["next_offset"] == b["offset"] for a, b in zip(decoded, decoded[1:]))
    assert sum(len(f["entries"]) for f in decoded) == 12


def test_an_entry_over_the_cap_is_skipped_but_its_bytes_are_counted():
    huge = b'{"x":"' + b"y" * nodelink.MAX_ENTRY_BYTES + b'"}\n'
    data = b'{"a":1}\n' + huge + b'{"b":2}\n'
    frames, next_offset = nodelink.transcript_frames("s1", 0, 0, data)
    entries = [e for f in frames for e in decode(f, NODE_FRAMES)["entries"]]
    assert entries == ['{"a":1}\n', '{"b":2}\n'] and next_offset == len(data)


def test_hub_session_ids_are_prefixed_by_node():
    assert nodelink.hub_session_id("3f2a1c9e", "abc-123") == "3f2a1c-abc-123"


def test_a_frame_with_no_fields_encodes():
    assert decode(encode("bye"), NODE_FRAMES) == {"t": "bye"}
    assert decode(encode("unpaired"), HUB_FRAMES) == {"t": "unpaired"}
