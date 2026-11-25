"""One sound per session: an optional short tone before a background session's report, the same one for a session every
time (docs/features/session-tones.md). With five sessions the listener waits for the name to know who is reporting; a
tone says it in a fifth of a second. Off unless turned on (the setting "reports.tones").

Eight tones, each a motif of one to three notes inside MAX_SECS, at a quiet level. They differ in pitch, in contour and
in rhythm, not in loudness or timbre: the same soft sine with its octave as the waiting sound (thinking.py).

Distinct is measured here, not claimed. `distance` is one minus the cosine likeness of two sounds' third-octave spectra
taken every FRAME_SECS over the same span: 0 for the same sound at any loudness, 1 for sounds with no energy in the same
band at the same moment. A third of an octave is about what the ear resolves as one band, so two notes a semitone
apart count as nearly the same, and two motifs with the same notes in another rhythm count as different only where
they do not overlap. No two tones, and no tone and one of Pointe's other sounds (the waiting sound, the two-note chime),
are closer than MIN_DISTANCE (tests/test_tones.py). That is a necessary check, not proof that people can name a session
from its tone: the listening test for that (ten people, five minutes of use, above 80% right) is still owed.

A session's tone starts from a hash of its name and moves to the next free one when another session on the voice has
it, so sessions on the voice do not share a tone until there are more than eight. The daemon keeps it with the session.

    python3 -I pointe/tones.py     the table of distances, as docs/features/session-tones.md carries it
"""

import hashlib
import itertools
from dataclasses import dataclass

import numpy as np

# The words, on the page (ui_tones.html) and in both apps (TonesCopy), word for word.
COPY = {
    "setting": "Session tones",
    "hint": "A short tone before a background session's report, the same one for that session every time, so you know who is "
            "reporting before the first word.",
    "row": "tone: {name}",
}

LEVEL = 0.12  # of full scale: the waiting sound is a tenth, the chimes a quarter
MAX_SECS = 0.32
MIN_DISTANCE = 0.5
FRAME_SECS = 0.03
_RAMP_SECS = 0.012  # each note fades in and out: no click
_BANDS = 200.0 * 2 ** (np.arange(0, 19) / 3)  # third-octave edges, 200 Hz to 12.8 kHz

_C4, _G4, _A4, _C5, _D5, _E5, _A5, _C6, _D6, _E6, _G6 = (261.63, 392.0, 440.0, 523.25, 587.33, 659.25, 880.0, 1046.5, 1174.66,
                                                         1318.51, 1567.98)


@dataclass(frozen=True)
class Tone:
    name: str  # a word for it on the screen and in the docs
    notes: tuple  # (hertz, seconds) in order; 0 hertz is a rest


PALETTE = (
    Tone("rise", ((_G4, 0.12), (_C5, 0.18))),
    Tone("fall", ((_E6, 0.12), (_A5, 0.18))),
    Tone("double", ((_E5, 0.07), (0, 0.05), (_E5, 0.07))),
    Tone("long", ((_C4, 0.30),)),
    Tone("leap", ((_A4, 0.08), (_A5, 0.08), (0, 0.02), (_E6, 0.10))),
    Tone("triple", ((_G6, 0.06), (0, 0.04), (_G6, 0.06), (0, 0.04), (_G6, 0.06))),
    Tone("dip", ((_D6, 0.10), (_G4, 0.10), (_D6, 0.10))),
    Tone("late", ((0, 0.14), (_D5, 0.07), (0, 0.03), (_C6, 0.06))),
)


def render(notes, rate: int) -> np.ndarray:
    """The notes as one wave, peak at LEVEL: each a sine with its octave, faded at both ends."""
    parts = []
    for hz, secs in notes:
        t = np.arange(int(rate * secs)) / rate
        if not hz:
            parts.append(np.zeros(len(t)))
            continue
        edge = np.minimum(t, secs - t).clip(0, _RAMP_SECS) / _RAMP_SECS
        window = 0.5 - 0.5 * np.cos(np.pi * edge)
        parts.append((np.sin(2 * np.pi * hz * t) + 0.3 * np.sin(2 * np.pi * 2 * hz * t)) / 1.3 * window)
    return np.concatenate(parts) * LEVEL


def wave(index: int, rate: int) -> np.ndarray:
    return render(PALETTE[index % len(PALETTE)].notes, rate)


def pcm(index: int, rate: int) -> bytes:
    """The tone as 16-bit mono audio at `rate`, for the call's own output."""
    return (wave(index, rate) * 32767).astype(np.int16).tobytes()


def _spectra(sound: np.ndarray, rate: int) -> np.ndarray:
    """Energy in each third-octave band, every FRAME_SECS, over MAX_SECS and a little more; as a unit vector."""
    size, frames = int(rate * FRAME_SECS), int(round((MAX_SECS + 0.04) / FRAME_SECS))
    sound = np.concatenate([np.asarray(sound, dtype=np.float64), np.zeros(max(0, size * frames - len(sound)))])[:size * frames]
    hz = np.fft.rfftfreq(size, 1 / rate)
    rows = []
    for i in range(frames):
        power = np.abs(np.fft.rfft(sound[i * size:(i + 1) * size] * np.hanning(size))) ** 2
        rows.append([power[(hz >= low) & (hz < high)].sum() for low, high in zip(_BANDS[:-1], _BANDS[1:])])
    spectra = np.sqrt(np.array(rows))
    return spectra / (np.linalg.norm(spectra) or 1.0)


def distance(a: np.ndarray, b: np.ndarray, rate: int, rate_b: int | None = None) -> float:
    """How unlike two sounds are, 0 to 1 (the module's own words say how it is measured)."""
    return float(max(0.0, 1.0 - (_spectra(a, rate) * _spectra(b, rate_b or rate)).sum()))


def assign(name: str, taken) -> int:
    """The tone for a session named `name`: from a hash of the name, moved on past the tones in `taken` (the other
    sessions' on the voice). The same name with the same others gets the same tone."""
    used = set(taken)
    start = int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "big") % len(PALETTE)
    for step in range(len(PALETTE)):
        index = (start + step) % len(PALETTE)
        if index not in used:
            return index
    return start  # more sessions than tones: shared


def status(index: int | None) -> dict | None:
    return None if index is None else {"index": index, "name": PALETTE[index % len(PALETTE)].name}


def table(rate: int = 24000) -> str:
    """The distance between every two tones, as a Markdown table, and the closest pair."""
    names = [t.name for t in PALETTE]
    waves = [wave(i, rate) for i in range(len(PALETTE))]
    lines = ["| | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for i, name in enumerate(names):
        cells = ["" if j == i else f"{distance(waves[i], waves[j], rate):.2f}" for j in range(len(names))]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    apart, a, b = min((distance(waves[i], waves[j], rate), names[i], names[j]) for i, j in itertools.combinations(range(len(names)), 2))
    lines.append("")
    lines.append(f"The closest two are {a} and {b}, {apart:.2f} apart; the threshold is {MIN_DISTANCE:.2f}.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(table())
