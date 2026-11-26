"""The bot's voice through a bad path, on a fake clock: when the daemon sends each chunk (phone.next_send_at, as the
transport paces it), when it arrives over one TCP connection (tests/netshaper.py's model: latency, jitter, a lost
segment held a retransmission timeout with everything behind it), and what the listener hears from it. Deterministic
for a seed; no socket, no sleep.

Two listeners, each as its client plays:
- the page (pointe/ui.html, the `player` worklet): from dry, waits until PAGE_HOLD is in hand or it has waited that
  long, then plays what it has; tests/test_playout_gaps.py runs the worklet itself on the same arrivals to check this;
- the apps (JitterBuffer in apps/PointeKit/Sources/PointeKit/LinkPolicy.swift, mirrored here): the same, with a target
  that grows after a gap and comes down when calm.

A gap is the speaker silent while the same reply is still to come: what a person hears as the voice breaking.
"""

import random
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pointe"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import phone  # noqa: E402
from netshaper import PROFILES, Profile  # noqa: E402

CHUNK = 0.04  # pipecat's output chunk: audio_out_10ms_chunks = 4
APPS_0_8_TARGETS = (0.1, 0.06, 0.4)  # the apps' JitterBuffer (start, min, max) before 0.10.1, for "before" runs
PAGE_HOLD = 0.3  # pointe/ui.html, the player worklet's HOLD: the apps' start target
VOICE_SPEED = 4.0  # how much faster than real time the voice service makes speech, after its first byte


def send_times(secs: float, start: float, lead: float) -> list[float]:
    """When the transport writes each chunk of a reply asked for at `start`: no earlier than the voice service made it,
    and no earlier than its pacing clock allows (pipecat's FastAPIWebsocketOutputTransport.write_audio_frame: write,
    then sleep until the clock says the next may go)."""
    times, clock, awake = [], 0.0, start
    for k in range(round(secs / CHUNK)):
        made = start + (k + 1) * CHUNK / VOICE_SPEED
        at = max(made, awake)
        times.append(at)
        clock = phone.next_send_at(clock, at, CHUNK, lead)
        awake = max(at, clock)
    return times


class Path_:
    """One TCP connection's delivery, as tests/netshaper.py shapes it: each message `latency` later plus up to `jitter`,
    a lost one a retransmission timeout later, and never before the one ahead of it."""

    def __init__(self, profile: Profile, seed: int):
        self.p, self.rng, self.last = profile, random.Random(seed), 0.0

    def arrive(self, sent: float) -> float:
        p = self.p
        due = sent + (p.latency_ms + self.rng.uniform(0, p.jitter_ms)) / 1000
        if p.loss and self.rng.random() < p.loss:
            due += max(0.2, 2 * (p.latency_ms + p.jitter_ms) / 1000)
        self.last = max(self.last, due)
        return self.last


class JitterBuffer:
    """LinkPolicy.swift's JitterBuffer, line for line: tests/test_playout_gaps.py checks the constants still agree."""

    MIN_TARGET, MAX_TARGET, START_TARGET, SAME_REPLY, CALM = 0.2, 0.6, 0.3, 1.0, 20.0

    def __init__(self, fixed: float | None = None, targets: tuple[float, float, float] | None = None):
        """`fixed`: a target that never moves (the page's hold). `targets`: (start, min, max) other than these."""
        if fixed is not None:
            self.MIN_TARGET = self.MAX_TARGET = self.START_TARGET = fixed
        if targets is not None:
            self.START_TARGET, self.MIN_TARGET, self.MAX_TARGET = targets
        self.target, self.underruns, self.held, self.held_since = self.START_TARGET, 0, 0.0, None
        self.until, self.last_underrun, self.dry_at = 0.0, 0.0, None

    def arrived(self, secs: float, now: float) -> bool:
        if self.until > now:
            self.until += secs
            return True
        if self.until > 0:
            self.dry_at = self.until
        self.until = 0.0
        if self.dry_at is not None and self.held_since is None:
            if now - self.dry_at < self.SAME_REPLY:
                self.underruns += 1
                self.target = min(self.MAX_TARGET, self.target * 1.5 + 0.02)
                self.last_underrun = now
            elif now - self.last_underrun > self.CALM:
                self.target = max(self.MIN_TARGET, self.target - 0.02)
            self.dry_at = None
        self.held += secs
        self.held_since = now if self.held_since is None else self.held_since
        return self.release(now)

    def due(self) -> float | None:
        return None if self.held_since is None else self.held_since + self.target

    def release(self, now: float) -> bool:
        if self.held_since is None or not (self.held >= self.target or now - self.held_since >= self.target - 1e-6):
            return False
        self.until, self.held, self.held_since = now + self.held, 0.0, None
        return True


class Speaker:
    """What the listener hears: chunks given to it play back to back; a gap is silence inside one reply."""

    def __init__(self):
        self.playing_until, self.gaps, self.gap_secs = 0.0, 0, 0.0
        self.reply_end: dict[int, float] = {}
        self.first_sound: dict[int, float] = {}

    def play(self, now: float, reply: int, secs: float) -> None:
        start = max(now, self.playing_until)
        if reply in self.reply_end and start > self.reply_end[reply] + 1e-9:
            self.gaps += 1
            self.gap_secs += start - self.reply_end[reply]
        self.first_sound.setdefault(reply, start)
        self.playing_until = self.reply_end[reply] = start + secs


@dataclass
class Result:
    gaps_per_min: float
    gap_ms_per_min: float
    first_sound_ms: float  # from the reply being asked for to its first sound, on average


def replies(seed: int, count: int = 40) -> list[tuple[float, float]]:
    """(asked at, seconds of speech): replies of 2 to 14 s with the user's turn between them."""
    rng, t, out = random.Random(seed), 1.0, []
    for _ in range(count):
        secs = round(rng.uniform(2, 14) / CHUNK) * CHUNK
        out.append((t, secs))
        t += secs + rng.uniform(4, 10)
    return out


def arrivals(profile: str | Profile, lead: float, seed: int = 1) -> tuple[list[tuple[float, float]], list[tuple[float, int]]]:
    """The replies of `replies(seed)`, and when each chunk of them arrives sent with `lead` over `profile`."""
    path = Path_(PROFILES[profile] if isinstance(profile, str) else profile, seed)
    talk = replies(seed)
    return talk, [(path.arrive(sent), n) for n, (start, secs) in enumerate(talk) for sent in send_times(secs, start, lead)]


def listen(client: str, profile: str | Profile, lead: float, seed: int = 1, before: bool = False) -> Result:
    """`client` "page" or "app" hearing `replies(seed)` sent with `lead` over `profile`; `before`: the client as it
    was before 0.10.1 (the page held nothing, the apps' targets were APPS_0_8_TARGETS)."""
    talk, arrived = arrivals(profile, lead, seed)
    return hear(client, talk, arrived, before)


def hear(client: str, talk: list[tuple[float, float]], arrived: list[tuple[float, int]], before: bool = False) -> Result:
    """What `client` hears of the replies `talk` from chunks arriving at `arrived` (seconds, reply), in order."""
    if client == "page":
        buffer = JitterBuffer(fixed=0.0 if before else PAGE_HOLD)
    else:
        buffer = JitterBuffer(targets=APPS_0_8_TARGETS if before else None)
    speaker, held = Speaker(), []

    def release(now: float) -> None:
        for reply in held:
            speaker.play(now, reply, CHUNK)
        held.clear()

    for at, reply in arrived:
        while (due := buffer.due()) is not None and due <= at and buffer.release(due):
            release(due)
        held.append(reply)
        if buffer.arrived(CHUNK, at):
            release(at)
    if (due := buffer.due()) is not None and buffer.release(due):
        release(due)
    return result(talk, speaker.gaps, speaker.gap_secs, speaker.first_sound)


def result(talk: list[tuple[float, float]], gaps: int, gap_secs: float, first_sound: dict[int, float]) -> Result:
    minutes = sum(secs for _, secs in talk) / 60
    waits = [first_sound[n] - start for n, (start, _) in enumerate(talk)]
    return Result(round(gaps / minutes, 2), round(gap_secs * 1000 / minutes), round(1000 * sum(waits) / len(waits)))


def mean(runs: list[Result]) -> Result:
    n = len(runs)
    return Result(round(sum(r.gaps_per_min for r in runs) / n, 2), round(sum(r.gap_ms_per_min for r in runs) / n),
                  round(sum(r.first_sound_ms for r in runs) / n))
