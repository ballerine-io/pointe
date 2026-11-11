"""Cut one recorded take into the demo video: the page (or the iPhone) on the left, both Claude Code terminals on the
right, captions from what was actually said, and every cut marked with the time it skipped.

    uv run python -I demo/compose.py demo/out/take-N [--fps 30]

Writes demo/out/take-N/pointe-demo.mp4 and pointe-demo.srt. ffmpeg here has no text filters, so frames are drawn with
Pillow and piped in.
"""

import argparse
import bisect
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
PAGE = (0, 0, 1100, 940)
TERM = (1100, 0, 1920, 940)
BAR = (0, 940, 1920, 1080)
RATE = 48000
BG = (11, 16, 24)
ORANGE = (255, 79, 31)
TEXT = (242, 240, 238)
MUTED = (142, 152, 168)
CACHE = Path(__file__).resolve().parents[1] / "tests" / "e2e" / ".cache"
MENLO = "/System/Library/Fonts/Menlo.ttc"
SANS = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
CHAPTERS = {
    "connect": "Connect",
    "a: what did they do, switch by name": "Two sessions, one voice",
    "b: a read-out approval by voice": "A command read out, approved by voice",
    "b: a complex command, approved on the page": "Too complex to read out: shown exactly, tapped",
    "c: just listen": "Thinking out loud: it stays quiet",
    "d: by the way, while it works": "A side question, answered by a copy of the session",
    "e: the same call on the iPhone": "The same call on the iPhone app",
}
# Never on screen: whoever records the take.
REDACT = [(str(Path(__file__).resolve().parents[1]), "<pointe>"), (str(Path.home()), "~"), ("/private/tmp/demo/", "")]
TERM_COLORS = {"default": (214, 219, 226), "black": (60, 66, 76), "red": (255, 107, 107), "green": (126, 211, 129),
               "brown": (229, 192, 123), "yellow": (229, 192, 123), "blue": (110, 168, 254), "magenta": (199, 146, 234),
               "cyan": (102, 217, 239), "white": (230, 230, 230), "brightblack": (110, 118, 129)}


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def log_time(line: str) -> float:
    import time

    return time.mktime(time.strptime(line[:19], "%Y-%m-%d %H:%M:%S")) + float("0" + line[19:23])


# ---------- audio ----------

def bot_track(take: Path, t0: float, length: int) -> np.ndarray:
    """The bot's voice as the page played it: queued chunks back to back, emptied at each interrupt."""
    raw = np.fromfile(take / "bot.pcm", dtype=np.int16) if (take / "bot.pcm").exists() else np.zeros(0, np.int16)
    chunks = [(c["t"], raw[c["offset"] // 2:(c["offset"] + c["bytes"]) // 2]) for c in load_jsonl(take / "bot_index.jsonl")]
    cuts = sorted(e["at"] for e in load_jsonl(take / "events.jsonl") if e["kind"] == "interrupt")
    track = np.zeros(length, np.float32)
    cursor, placed = 0.0, []
    events = sorted([(t, 0, pcm) for t, pcm in chunks] + [(t, 1, None) for t in cuts], key=lambda e: (e[0], e[1]))
    for t, kind, pcm in events:
        if kind == 1:
            placed = [(s, p[: max(0, int((t - s) * 24000))]) for s, p in placed]
            cursor = t
            continue
        start = max(cursor, t)
        placed.append((start, pcm))
        cursor = start + len(pcm) / 24000
    for start, pcm in placed:
        if not len(pcm):
            continue
        up = np.interp(np.arange(len(pcm) * 2) / 2, np.arange(len(pcm)), pcm.astype(np.float32))
        i = int((start - t0) * RATE)
        if 0 <= i < length:
            track[i:i + len(up)] += up[: length - i]
    return track


def user_track(events: list[dict], t0: float, length: int) -> np.ndarray:
    track = np.zeros(length, np.float32)
    for e in events:
        if e["kind"] != "user":
            continue
        pcm = np.fromfile(CACHE / f"{e['cache']}.pcm", dtype=np.int16).astype(np.float32)
        i = int((e["start"] - t0) * RATE)
        if 0 <= i < length:
            track[i:i + len(pcm)] += pcm[: length - i]
    return track


def spans(track: np.ndarray, t0: float, threshold: float = 300, gap: float = 0.8) -> list[list[float]]:
    hop = RATE // 50
    loud = np.abs(track[: len(track) // hop * hop].reshape(-1, hop)).mean(axis=1) > threshold
    out: list[list[float]] = []
    for i in np.flatnonzero(loud):
        t = t0 + i / 50
        if out and t - out[-1][1] <= gap:
            out[-1][1] = t + 0.02
        else:
            out.append([t, t + 0.02])
    return out


# ---------- the cut ----------

def keep_segments(active: list[tuple[float, float]], t0: float, t1: float, pad: float = 0.5, max_gap: float = 2.0):
    """Keep what is said and done; shorten every quiet stretch longer than max_gap to max_gap, and say so."""
    merged: list[list[float]] = []
    for a, b in sorted((max(t0, a - pad), min(t1, b + pad)) for a, b in active):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    keep, previous = [], t0
    for a, b in merged + [[t1, t1]]:
        gap = a - previous
        if gap > max_gap:
            keep.append((previous, previous + max_gap / 2))
            keep.append((a - max_gap / 2, b))
        else:
            keep.append((previous, b))
        previous = b
    joined: list[list[float]] = []
    for a, b in keep:
        if b <= a:
            continue
        if joined and abs(a - joined[-1][1]) < 1e-6:
            joined[-1][1] = b
        else:
            joined.append([a, b])
    return joined


# ---------- drawing ----------

class Terminal:
    def __init__(self, path: Path, title: str):
        self.snaps = load_jsonl(path)
        self.times = [s["t"] for s in self.snaps]
        self.title = title
        self.font = ImageFont.truetype(MENLO, 12, index=0)
        self.bold = ImageFont.truetype(MENLO, 12, index=1)
        self.cache: dict[int, Image.Image] = {}

    def image(self, t: float, size: tuple[int, int]) -> Image.Image:
        i = bisect.bisect_right(self.times, t) - 1
        if i not in self.cache:
            self.cache = {i: self._draw(self.snaps[i] if i >= 0 else None, size)}
        return self.cache[i]

    def _draw(self, snap: dict | None, size: tuple[int, int]) -> Image.Image:
        img = Image.new("RGB", size, (16, 21, 30))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, size[0], 26], fill=(24, 31, 43))
        for k, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            d.ellipse([12 + k * 18, 8, 22 + k * 18, 18], fill=c)
        d.text((size[0] // 2, 13), self.title, fill=MUTED, font=self.font, anchor="mm")
        if not snap:
            return img
        cw, lh, x0, y0 = self.font.getlength("M"), 14.6, 14, 34
        for y, runs in enumerate(snap["rows"]):
            x = x0
            for text, fg, bg, bold, reverse in runs:
                for secret, shown in REDACT:
                    text = text.replace(secret, shown)
                fgc = _color(fg, TERM_COLORS["default"])
                bgc = _color(bg, None)
                if reverse:
                    fgc, bgc = bgc or (16, 21, 30), fgc
                if bgc:
                    d.rectangle([x, y0 + y * lh, x + cw * len(text), y0 + (y + 1) * lh], fill=bgc)
                if text.strip():
                    d.text((x, y0 + y * lh), text, fill=fgc, font=self.bold if bold else self.font)
                x += cw * len(text)
        return img


def _color(name: str, default):
    if name in ("default", None):
        return default
    if re.fullmatch(r"[0-9a-fA-F]{6}", name):
        return tuple(int(name[i:i + 2], 16) for i in (0, 2, 4))
    return TERM_COLORS.get(name, default)


def wrap(text: str, font, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if font.getlength(trial) > width and line:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + ([line] if line else [])


def captions(events: list[dict], log: list[str], bot_spans: list[list[float]], phone_from: float | None) -> list[dict]:
    """Who said what, when: the user's lines as synthesized, the bot's as the daemon spoke them, timed to its audio."""
    out = [{"start": e["start"], "end": e["end"] + 0.4, "who": "You", "text": e["text"]}
           for e in events if e["kind"] == "user"]
    said = [(log_time(line), line.split("speak: ", 1)[1].strip().strip("'\"")) for line in log if " - speak: " in line]
    free = list(bot_spans)
    for t, text in said:
        if phone_from and t >= phone_from:  # the phone played this one; it is not in the recorded audio
            words = len(text.split())
            out.append({"start": t + 0.8, "end": t + 0.8 + words / 2.6, "who": "Pointe, on the phone", "text": text})
            continue
        span = next((s for s in free if s[0] >= t - 0.3), None)
        if not span:
            continue
        free = free[free.index(span) + 1:]
        words = text.split()
        duration = span[1] - span[0]
        rate = len(words) / duration if 0.6 < len(words) / 2.6 / max(duration, 0.1) < 1.6 else 2.6
        shown = max(1, min(len(words), round(duration * rate + 0.5)))
        chunk, start = [], span[0]
        for k, word in enumerate(words[:shown]):  # a cut-off reply shows only what was heard
            chunk.append(word)
            if len(chunk) >= 16 or k == shown - 1 or (word.endswith((".", "?", "!")) and len(chunk) >= 6):
                end = start + len(chunk) / rate
                out.append({"start": start, "end": end + 0.3, "who": "Pointe", "text": " ".join(chunk)})
                chunk, start = [], end
    return sorted(out, key=lambda c: c["start"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("take", type=Path)
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args()
    take, fps = args.take, args.fps
    events = load_jsonl(take / "events.jsonl")
    log = (take / "daemon.log").read_text(errors="ignore").splitlines()
    beats = [(e["t"], e["name"]) for e in events if e["kind"] == "beat"]
    t0 = beats[0][0] - 0.3
    t1 = beats[-1][0] + 1.0
    length = int((t1 - t0) * RATE)
    bot = bot_track(take, t0, length)
    user = user_track(events, t0, length)
    phone_from = next((e["t"] for e in events if e["kind"] == "phone-video"), None)
    phone_beat = next((t for t, n in beats if n.startswith("e:")), None)

    bot_spans = spans(bot, t0)
    active = [(e["start"], e["end"]) for e in events if e["kind"] == "user"] + [tuple(s) for s in bot_spans]
    active += [(e["t"] - 1.0, e["t"] + 2.0) for e in events if e["kind"] in ("click", "phone", "typed", "phone-done", "request")]
    active += [(t, t + 1.2) for t, _ in beats]
    caps = captions(events, log, bot_spans, phone_from)
    active += [(c["start"], c["end"]) for c in caps if c["who"].startswith("Pointe, on")]
    segments = keep_segments(active, t0, t1)

    page_index = load_jsonl(take / "page_index.jsonl")
    page_times = [p["t"] for p in page_index]
    terms = [Terminal(take / "term-checkout.jsonl", "checkout · claude"), Terminal(take / "term-billing.jsonl", "billing · claude")]
    phone_frames = []
    if phone_from and (take / "phone.mp4").exists():
        frames_dir = take / "phone_frames"
        if not frames_dir.exists():
            frames_dir.mkdir()
            subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(take / "phone.mp4"), "-vf", "fps=15,scale=-2:900",
                            str(frames_dir / "%06d.jpg")], check=True)
        phone_frames = sorted(frames_dir.glob("*.jpg"))

    sans = ImageFont.truetype(SANS, 26)
    small = ImageFont.truetype(SANS, 17)
    tiny = ImageFont.truetype(SANS, 15)
    page_cache: dict[str, Image.Image] = {}
    clicks = [e for e in events if e["kind"] == "click"]

    out_mp4 = take / "pointe-demo.mp4"
    total = sum(b - a for a, b in segments)
    print(f"source {t1 - t0:.0f}s -> cut {total:.0f}s in {len(segments)} segments", flush=True)
    audio = np.concatenate([(user * 0.85 + bot)[int((a - t0) * RATE):int((b - t0) * RATE)] for a, b in segments])
    np.clip(audio, -32768, 32767).astype(np.int16).tofile(take / "mix.pcm")

    ffmpeg = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                               "-r", str(fps), "-i", "-", "-f", "s16le", "-ar", str(RATE), "-ac", "1", "-i", str(take / "mix.pcm"),
                               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "medium",
                               "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(out_mp4)],
                              stdin=subprocess.PIPE)
    srt, out_t = [], 0.0
    for n, (a, b) in enumerate(segments):
        skipped = a - segments[n - 1][1] if n else 0
        frames = int(round((b - a) * fps))
        for f in range(frames):
            t = a + f / fps
            canvas = Image.new("RGB", (W, H), BG)
            draw = ImageDraw.Draw(canvas)
            on_phone = phone_beat is not None and t >= (phone_from or 1e18)
            if on_phone and phone_frames:
                k = min(len(phone_frames) - 1, max(0, int((t - phone_from) * 15)))
                img = Image.open(phone_frames[k])
                canvas.paste(img, (PAGE[0] + (PAGE[2] - img.width) // 2, 20))
            else:
                i = bisect.bisect_right(page_times, t) - 1
                if i >= 0:
                    name = page_index[i]["file"]
                    if name not in page_cache:
                        page_cache.clear()
                        page_cache[name] = Image.open(take / "page" / name).convert("RGB")
                    canvas.paste(page_cache[name], (0, 0))
                for c in clicks:
                    age = t - c["t"]
                    if 0 <= age <= 0.8:
                        r = 14 + age * 40
                        draw.ellipse([c["x"] - r, c["y"] - r, c["x"] + r, c["y"] + r], outline=ORANGE, width=4)
            th = (TERM[3] - TERM[1]) // 2
            for k, term in enumerate(terms):
                canvas.paste(term.image(t, (TERM[2] - TERM[0], th - 2)), (TERM[0], TERM[1] + k * th + (2 if k else 0)))
            draw.line([TERM[0], 0, TERM[0], TERM[3]], fill=(32, 40, 54), width=2)
            draw.rectangle(BAR, fill=(8, 11, 17))
            chapter = next((CHAPTERS.get(name, "") for bt, name in reversed(beats) if bt <= t), "")
            draw.text((28, BAR[1] + 16), chapter.upper(), fill=ORANGE, font=tiny)
            label = "Real call, real Claude Code sessions. The user's voice is synthesized. Pauses shortened, marked."
            draw.text((W - 28, BAR[3] - 14), label, fill=(95, 107, 125), font=tiny, anchor="rs")
            if skipped > 0.5 and f < fps * 1.6:
                draw.text((W - 28, BAR[1] + 16), f"cut: {skipped:.0f} s skipped", fill=MUTED, font=small, anchor="ra")
            cap = next((c for c in reversed(caps) if c["start"] <= t <= c["end"]), None)
            if cap:
                who = cap["who"]
                color = ORANGE if who.startswith("Pointe") else (126, 211, 129)
                draw.text((28, BAR[1] + 48), who, fill=color, font=small)
                lines = wrap(cap["text"], sans, W - 340)[-2:]
                for j, line in enumerate(lines):
                    draw.text((220, BAR[1] + 42 + j * 34), line, fill=TEXT, font=sans)
            ffmpeg.stdin.write(canvas.tobytes())
        for c in caps:
            if a <= c["start"] < b:
                s = out_t + c["start"] - a
                srt.append((s, s + min(c["end"], b) - c["start"], f"{c['who']}: {c['text']}"))
        out_t += frames / fps
    ffmpeg.stdin.close()
    ffmpeg.wait()

    def stamp(x: float) -> str:
        return f"{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{int(x % 60):02d},{int(x % 1 * 1000):03d}"

    (take / "pointe-demo.srt").write_text("".join(f"{i + 1}\n{stamp(a)} --> {stamp(b)}\n{text}\n\n"
                                                  for i, (a, b, text) in enumerate(srt)))
    print(f"wrote {out_mp4} ({out_t:.0f}s)")
    sys.exit(ffmpeg.returncode)


main()
