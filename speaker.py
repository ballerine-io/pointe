"""Owner-voice lock: is this the owner talking? A speaker-verification model on this Mac, never a vendor.

The voiceprint is biometric data. It is computed and stored only here (`<state>/voiceprint/`, 0700, each file 0600),
deletable from the page and the app, and never sent anywhere. The model is a small open one (3D-Speaker ERes2Net, Apache-2.0)
run by sherpa-onnx; it downloads once, on first use, into `<state>/models/`.

What a lock level may do, and which way it fails, is decided here so the daemon has one rule to ask:

- The lock only narrows. Off is the old behaviour; every level above it removes what other voices can do. A match is
  never consent: an owner's "yes" still has to pass every rule a "yes" passed before.
- It fails closed. When it cannot tell (no model, a model error or timeout, too little audio, no voiceprint), the speech
  counts as not the owner's for what the level guards. A tap on the page or Face ID in the app still approves and typed
  words still reach Pointe, so failing closed costs convenience, never control. A "no" counts from anyone.

Short utterances are the weak point of every verifier: a lone half-second "yes" is not scored as confidently as a
sentence. `owner_confident` accepts a weaker score only right after a strong match on the same device profile.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
import urllib.request
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from loguru import logger

LEVELS = ("off", "approvals", "commands", "everything")
RATE = 16000  # what both clients send (phone.IN_RATE)

# Cosine similarity against the owner's centroid, chosen on synthetic voices (bench/results/speaker.md: EER 1.9% on
# sentences at 0.50, 2.7% on a lone "yes" at 0.32). Recorded owner samples should move them before a default other than
# "approvals" is offered.
T_HIGH = 0.55  # a confident match on its own, with MIN_SECS of speech: favours fewer false accepts over the EER point
T_LOW = 0.35  # enough only within a minute of a confident match on the same device profile (a short "yes")
MIN_SECS = 1.0
CONTINUITY_SECS = 60.0
SCORE_TIMEOUT_SECS = 0.6  # slower than this counts as not scored
MAX_SCORED_SECS = 8.0  # the newest speech of a long turn is scored, so a minute of talk costs the same as a sentence

ENROL_SECS = 25.0
ENROL_SEGMENTS = 5
ENROL_SEGMENT_MIN_SECS = 1.0
ENROL_MIN_RMS = 300.0  # int16: a whisper across the room is not enough to learn a voice from
ENROL_EXPIRES_SECS = 10 * 60  # an enrolment the call dropped out of waits this long to resume
IGNORED_KEPT = 10

# Read aloud during enrolment: three English, three Hebrew, identical on the page and in the app.
LINES = (
    "The quick brown fox jumps over the lazy dog near the riverbank.",
    "Please tell the build session to run the tests and report back.",
    "Seven bright kites drifted above the harbour on a windy afternoon.",
    "בוקר טוב, אני בודק שהמערכת מזהה את הקול שלי בצורה ברורה.",
    "תגיד לסשן של הבדיקות להריץ את כל הבדיקות ולדווח לי.",
    "שלושה עפיפונים צבעוניים עפו מעל הנמל ביום סוער.",
)

MODEL_NAME = "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
MODEL_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/{MODEL_NAME}"
MODEL_SHA256 = "1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b"
MODEL_MB = 40
MODEL_LICENSE = "Apache-2.0: 3D-Speaker ERes2Net base (modelscope iic/speech_eres2net_base_sv_zh-cn_3dspeaker_16k)"


@dataclass(frozen=True)
class Verdict:
    """How one utterance scored against the owner's voiceprint."""
    score: float | None  # None: not scored, and `why` says why
    secs: float
    device: str = ""  # the profile it matched best
    at: float = 0.0
    why: str = ""


def owner_confident(v: Verdict | None, previous: Verdict | None) -> bool:
    """A strong match on its own, or a weaker one within a minute of a strong match on the same device profile."""
    if v is None or v.score is None:
        return False
    if v.score >= T_HIGH and v.secs >= MIN_SECS:
        return True
    return bool(v.score >= T_LOW and strong(previous) and previous.device == v.device
                and 0 <= v.at - previous.at < CONTINUITY_SECS)


def strong(v: Verdict | None) -> bool:
    return v is not None and v.score is not None and v.score >= T_HIGH and v.secs >= MIN_SECS


def _slug(device: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", device.lower()).strip("-")[:40] or "this-device"


def _write_private(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


class Profiles:
    """One centroid per device the owner enrolled on. Files are 0600 in a 0700 folder."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.items: dict[str, dict] = {}  # slug -> {device, vector, seconds, segments, at}
        self.problem: str | None = None
        self.load()

    def load(self) -> None:
        self.items, self.problem = {}, None
        if not self.folder.is_dir():
            return
        for path in sorted(self.folder.glob("*.npz")):
            try:
                with np.load(path, allow_pickle=False) as z:
                    vector = np.asarray(z["vector"], dtype=np.float32)
                    self.items[path.stem] = {"device": str(z["device"]), "vector": vector / np.linalg.norm(vector),
                                             "seconds": float(z["seconds"]), "segments": int(z["segments"]),
                                             "at": float(z["at"])}
            except Exception as e:  # a damaged file must not read as "no voiceprint": that would lift the lock
                self.problem = f"a voiceprint file could not be read ({type(e).__name__}); re-enrol or delete it"
                logger.warning(f"voice lock: {self.problem}")

    @property
    def enrolled(self) -> bool:
        return bool(self.items) or self.problem is not None

    def save(self, device: str, vector: np.ndarray, seconds: float, segments: int) -> None:
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.folder, 0o700)
        slug = _slug(device)
        import io

        buf = io.BytesIO()
        at = time.time()
        np.savez(buf, vector=vector.astype(np.float32), device=np.array(device[:60]), seconds=np.array(seconds),
                 segments=np.array(segments), at=np.array(at))
        _write_private(self.folder / f"{slug}.npz", buf.getvalue())
        self.items[slug] = {"device": device[:60], "vector": vector / np.linalg.norm(vector), "seconds": seconds,
                            "segments": segments, "at": at}

    def delete(self, device: str | None = None) -> int:
        """One device's profile, or every file in the folder (damaged ones too). Returns how many went."""
        if not self.folder.is_dir():
            return 0
        if device is None:
            paths = list(self.folder.glob("*.npz")) + list(self.folder.glob("*.tmp"))
        else:
            slug = next((k for k, v in self.items.items() if v["device"] == device), _slug(device))
            paths = [self.folder / f"{slug}.npz"]
        gone = 0
        for path in paths:
            try:
                path.unlink()
                gone += 1
            except FileNotFoundError:
                pass
        self.load()
        return gone

    def best(self, vector: np.ndarray) -> tuple[float, str]:
        if not self.items:
            return -1.0, ""
        v = vector / np.linalg.norm(vector)
        scored = [(float(np.dot(v, p["vector"])), p["device"]) for p in self.items.values()]
        return max(scored)

    def devices(self) -> list[dict]:
        return [{"device": p["device"], "seconds": round(p["seconds"], 1), "segments": p["segments"], "enrolled_at": p["at"]}
                for p in sorted(self.items.values(), key=lambda p: p["at"])]


class Embedder:
    """The speaker model, loaded on first use. Downloads it once (checksum pinned) when it is missing."""

    def __init__(self, folder: Path) -> None:
        self.path = folder / MODEL_NAME
        self.state = "ready" if self.path.exists() else "missing"  # missing | downloading | ready | failed
        self.error: str | None = None
        self._extractor = None

    @property
    def loaded(self) -> bool:
        return self._extractor is not None

    def ensure(self) -> bool:
        """Blocking: download and load. False (with `error`) when it cannot."""
        if self._extractor is not None:
            return True
        try:
            if not self.path.exists():
                self.state = "downloading"
                logger.info(f"voice lock: downloading the speaker model once ({MODEL_MB} MB, {MODEL_LICENSE}) "
                            f"from {MODEL_URL}")
                self.path.parent.mkdir(parents=True, exist_ok=True)
                part = self.path.with_suffix(".part")
                with urllib.request.urlopen(MODEL_URL, timeout=60) as r, open(part, "wb") as f:
                    while chunk := r.read(1 << 20):
                        f.write(chunk)
                digest = hashlib.sha256(part.read_bytes()).hexdigest()
                if digest != MODEL_SHA256:
                    part.unlink(missing_ok=True)
                    raise ValueError("the downloaded model's checksum does not match")
                os.replace(part, self.path)
            import sherpa_onnx

            self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
                sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(self.path), num_threads=1))
            self.state, self.error = "ready", None
            return True
        except Exception as e:
            self.state, self.error = "failed", f"{type(e).__name__}: {e}"[:200]
            logger.warning(f"voice lock: the speaker model is unavailable ({self.error})")
            return False

    def embed(self, samples: np.ndarray) -> np.ndarray:
        """float32 samples in [-1, 1] at 16 kHz -> a unit vector."""
        if not self.ensure():
            raise RuntimeError(self.error or "no speaker model")
        stream = self._extractor.create_stream()
        stream.accept_waveform(RATE, samples)
        stream.input_finished()
        v = np.asarray(self._extractor.compute(stream), dtype=np.float32)
        return v / np.linalg.norm(v)


class Collector:
    """The user's voiced audio since the last utterance was taken: what the next final transcript is scored on."""

    PREROLL_SECS = 0.3  # the voice detector starts a beat after the voice does
    MAX_SECS = 20.0

    def __init__(self) -> None:
        self._buf = bytearray()
        self._preroll: deque = deque()
        self._preroll_bytes = 0
        self._open = False

    def frame(self, pcm: bytes, voiced: bool) -> None:
        if voiced:
            if not self._open:
                self._buf.extend(b"".join(self._preroll))
                self._preroll.clear()
                self._preroll_bytes = 0
                self._open = True
            self._buf.extend(pcm)
            limit = int(self.MAX_SECS * RATE * 2)
            if len(self._buf) > limit:
                del self._buf[:len(self._buf) - limit]
            return
        self._open = False
        self._preroll.append(pcm)
        self._preroll_bytes += len(pcm)
        while self._preroll_bytes > self.PREROLL_SECS * RATE * 2 and len(self._preroll) > 1:
            self._preroll_bytes -= len(self._preroll.popleft())

    def take(self) -> bytes:
        data, self._buf = bytes(self._buf), bytearray()
        return data

    def clear(self) -> None:
        self._buf = bytearray()
        self._preroll.clear()
        self._preroll_bytes = 0
        self._open = False


def _samples(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm[:len(pcm) - len(pcm) % 2], dtype=np.int16).astype(np.float32) / 32768.0


def secs_of(pcm: bytes) -> float:
    return len(pcm) / 2 / RATE


@dataclass
class Enrolment:
    device: str
    started_at: float
    vectors: list
    seconds: float = 0.0
    rejected: int = 0
    last_reason: str = ""

    @property
    def line(self) -> int:
        return len(self.vectors) % len(LINES)

    @property
    def progress(self) -> float:
        return round(min(1.0, self.seconds / ENROL_SECS, len(self.vectors) / ENROL_SEGMENTS), 2)

    @property
    def done(self) -> bool:
        return self.seconds >= ENROL_SECS and len(self.vectors) >= ENROL_SEGMENTS


class VoiceLock:
    """The daemon's one place for "is this the owner?": the voiceprint, the model, the call's verdicts."""

    def __init__(self, folder: Path, models: Path, embedder: Embedder | None = None) -> None:
        self.profiles = Profiles(folder)
        self.embedder = embedder or Embedder(models)
        self.collector = Collector()
        self.enrolment: Enrolment | None = None
        self.last: Verdict | None = None  # the newest scored utterance
        self.last_strong: Verdict | None = None  # the newest confident one: what a short "yes" leans on
        self.ignored: deque = deque(maxlen=IGNORED_KEPT)  # {at, secs, text?}: never in a log
        self.ignored_count = 0
        self.unsure_streak = 0  # uncertain yeses in a row: after 3, the clients say "tap, or re-enrol"
        self.degraded: str | None = None  # why it could not check the last utterance

    @property
    def enrolled(self) -> bool:
        return self.profiles.enrolled

    def wanted(self, level: str) -> bool:
        """Score utterances only when something reads the score."""
        return level != "off" or self.enrolment is not None

    def problem(self, level: str) -> str | None:
        """Why the lock cannot check voices right now, while it is on. It then fails closed."""
        if level == "off":
            return None
        if self.profiles.problem:
            return self.profiles.problem
        if not self.profiles.items:
            return "no voiceprint is stored"
        if self.embedder.state == "failed":
            return f"the speaker model could not load ({self.embedder.error})"
        return self.degraded

    def load_soon(self) -> None:
        """Download and load the model in the background, so no utterance waits on it."""
        if getattr(self.embedder, "loaded", True) or self._loading is not None and not self._loading.done():
            return
        try:
            self._loading = asyncio.get_running_loop().create_task(asyncio.to_thread(self.embedder.ensure))
        except RuntimeError:  # no loop: the first judge() starts it
            pass

    _loading: asyncio.Task | None = None

    async def _vector(self, pcm: bytes) -> np.ndarray | str:
        """The embedding, or why there is none. Never waits for a download: that would hold up the call."""
        if not getattr(self.embedder, "loaded", True):
            self.load_soon()
            return "the speaker model is still loading" if self.embedder.state != "failed" else \
                f"the speaker model could not load ({self.embedder.error})"
        samples = _samples(pcm)[-int(MAX_SCORED_SECS * RATE):]
        try:
            vector = await asyncio.wait_for(asyncio.to_thread(self.embedder.embed, samples), SCORE_TIMEOUT_SECS)
        except Exception as e:  # a timeout, a model error: not scored, so not the owner
            self.degraded = f"the speaker model did not answer ({type(e).__name__})"
            logger.warning(f"voice lock: {self.degraded}")
            return self.degraded
        self.degraded = None
        return vector

    async def judge(self, now: float | None = None) -> Verdict:
        """Score the call's audio since the last utterance against every device profile (the best wins); while
        enrolling, learn from it instead."""
        now = time.time() if now is None else now
        pcm = self.collector.take()
        secs = secs_of(pcm)
        if self.enrolment is not None:
            vector = await self._vector(pcm) if secs >= ENROL_SEGMENT_MIN_SECS else "too short"
            if isinstance(vector, str):
                self.enrolment.rejected += 1
                self.enrolment.last_reason = vector
            else:
                self._enrol(vector, pcm, secs)
            v = Verdict(None, secs, at=now, why="enrolling")
        else:
            v = await self.score(pcm, now)
        self.last = v
        if strong(v):
            self.last_strong = v
        return v

    async def score(self, pcm: bytes, now: float | None = None) -> Verdict:
        """One stretch of audio against the voiceprint. Not scored (score None) whenever it cannot tell."""
        now = time.time() if now is None else now
        secs = secs_of(pcm)
        if secs < 0.3:
            return Verdict(None, secs, at=now, why="too little audio")
        if not self.profiles.items:
            return Verdict(None, secs, at=now, why="no voiceprint")
        vector = await self._vector(pcm)
        if isinstance(vector, str):
            return Verdict(None, secs, at=now, why=vector)
        score, device = self.profiles.best(vector)
        return Verdict(round(score, 3), secs, device, now)

    def confident(self, v: Verdict | None) -> bool:
        return owner_confident(v, self.last_strong)

    def ignore(self, v: Verdict, text: str | None = None) -> None:
        """Speech the lock kept from Pointe. The journal gets its length and score, never its words."""
        self.ignored_count += 1
        item = {"at": v.at or time.time(), "secs": round(v.secs, 1)}
        if text:
            item["text"] = text[:200]  # shown on the screen at the Commands level; kept in memory only
        self.ignored.append(item)
        score = "not scored" if v.score is None else f"score {v.score:.2f}"
        logger.info(f"ignored: not the owner ({v.secs:.1f} s, {score})")

    # ---- enrolment ----

    def start_enrolment(self, device: str) -> None:
        self.enrolment = Enrolment(device=device.strip()[:60] or "This device", started_at=time.time(), vectors=[])
        self.collector.clear()

    def cancel_enrolment(self) -> None:
        self.enrolment = None

    def expire(self, now: float | None = None) -> None:
        e = self.enrolment
        if e is not None and (time.time() if now is None else now) - e.started_at > ENROL_EXPIRES_SECS:
            logger.info("voice lock: an unfinished enrolment expired")
            self.enrolment = None

    def _enrol(self, vector: np.ndarray, pcm: bytes, secs: float) -> None:
        e = self.enrolment
        if float(np.sqrt(np.mean((_samples(pcm) * 32768) ** 2))) < ENROL_MIN_RMS:
            e.rejected += 1
            e.last_reason = "too quiet"
            return
        e.vectors.append(vector)
        e.seconds += min(secs, MAX_SCORED_SECS)
        e.last_reason = ""
        if e.done:
            centroid = np.mean(np.stack(e.vectors), axis=0)
            self.profiles.save(e.device, centroid / np.linalg.norm(centroid), e.seconds, len(e.vectors))
            logger.info(f"voice lock: enrolled ({len(e.vectors)} segments, {e.seconds:.0f} s)")
            self.enrolment = None
            self.last_strong = None

    def status(self, level: str) -> dict:
        e = self.enrolment
        v = self.last
        return {
            "level": level,
            "enrolled": self.enrolled,
            "devices": self.profiles.devices(),
            "enrolling": None if e is None else {
                "device": e.device, "progress": e.progress, "line": e.line, "text": LINES[e.line],
                "seconds": round(e.seconds, 1), "segments": len(e.vectors), "rejected": e.rejected,
                "last_reason": e.last_reason},
            "lines": list(LINES),
            "model": self.embedder.state,
            "problem": self.problem(level),
            "ignored": {"count": self.ignored_count, "last_at": self.ignored[-1]["at"] if self.ignored else None,
                        "recent": list(self.ignored)},
            "speaker": None if v is None else {"owner": None if v.score is None else self.confident(v),
                                               "score": v.score, "at": v.at},
            "unsure_streak": self.unsure_streak,
        }
