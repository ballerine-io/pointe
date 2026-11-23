"""Render a scene of the site's story as one film: tools/scene_film/<name>.html stepped frame by frame in headless
Chrome (the page holds its own transitions at the film's clock: step(t)), then ffmpeg: the footage under the left column, the
frames over it, the mixed voices on it. Writes site/pointe/scenes/<name>-<look>.mp4 and .webm, a poster and the captions.

    uv run --locked python tools/scene_film/render.py desk <footage.mp4> <voices.mp3> <cues.json> [work folder] [--encode: the frames are already in the work folder]

Chrome runs with a mock keychain (the login keychain is never asked). Invented sessions only; nothing is fetched.
"""
import asyncio, base64, json, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import page_rig  # noqa: E402

FPS, W, H, SCALE, CLIP = 30, 1280, 720, 1.5, 492


async def frames(name: str, look: str, total: float, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    shim = out.parent / "chrome.sh"
    shim.write_text(f'#!/bin/sh\nexec "{page_rig.CHROME}" --use-mock-keychain --password-store=basic --allow-file-access-from-files "$@"\n')
    shim.chmod(0o755)
    real, page_rig.CHROME = page_rig.CHROME, str(shim)

    async def ready(self):
        await asyncio.sleep(1.5)
    page_rig.Chrome.wait_for_page = ready
    try:
        async with page_rig.Browser() as browser:
            page = await browser.open((ROOT / "tools" / "scene_film" / f"{name}.html").as_uri())
            await page.cdp("Emulation.setDeviceMetricsOverride", {"width": W, "height": H, "deviceScaleFactor": SCALE, "mobile": False})
            await page.cdp("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": look}]})
            await page.cdp("Emulation.setDefaultBackgroundColorOverride", {"color": {"r": 0, "g": 0, "b": 0, "a": 0}})
            await page.eval("document.fonts.ready.then(() => true)")
            await asyncio.sleep(0.5)
            count = int(total * FPS) + 1
            for n in range(count):
                await page.eval(f"step({n / FPS:.4f})")
                data = (await page.cdp("Page.captureScreenshot", {"format": "png"}))["data"]
                (out / f"{n:05d}.png").write_bytes(base64.b64decode(data))
                if n % 300 == 0:
                    print(look, n, "of", count, flush=True)
            return count
    finally:
        page_rig.CHROME = real


def film(name: str, look: str, work: Path, footage: Path, voices: Path, total: float) -> None:
    site = ROOT / "site" / "pointe" / "scenes"
    cw, fh = int(CLIP * SCALE), int(H * SCALE)
    # the footage plays forward then backward, so its loop has no jump; it fills the left column as `object-fit: cover` would
    graph = (f"[0:v]fps={FPS},scale=-2:{fh}:flags=lanczos,split[f][r0];[r0]reverse[r];[f][r]concat=n=2,loop=loop=-1:size=32767,"
             f"crop={cw}:{fh},hqdn3d=6:4:9:6,pad={int(W * SCALE)}:{fh}:0:0:color=black[bg];[1:v]format=rgba[ui];[bg][ui]overlay=shortest=1,format=yuv420p[v]")
    common = ["ffmpeg", "-v", "error", "-y", "-i", str(footage), "-framerate", str(FPS), "-i", str(work / look / "%05d.png"), "-i", str(voices),
              "-filter_complex", graph, "-map", "[v]", "-map", "2:a", "-t", f"{total:.2f}", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact"]
    subprocess.run([*common, "-c:v", "libx264", "-preset", "slow", "-crf", "32", "-profile:v", "high", "-pix_fmt", "yuv420p", "-g", "60",
                    "-bsf:v", "filter_units=remove_types=6", "-c:a", "aac", "-b:a", "80k", "-ac", "1", "-movflags", "+faststart", str(site / f"{name}-{look}.mp4")], check=True)
    subprocess.run([*common, "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "45", "-row-mt", "1", "-deadline", "good", "-cpu-used", "2", "-g", "120",
                    "-c:a", "libopus", "-b:a", "48k", "-ac", "1", str(site / f"{name}-{look}.webm")], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "16", "-i", str(site / f"{name}-{look}.mp4"), "-frames:v", "1", "-vf", "scale=1280:-2:flags=lanczos",
                    "-q:v", "4", "-map_metadata", "-1", "-fflags", "+bitexact", str(site / f"{name}-{look}.jpg")], check=True)


def captions(name: str, cues: list[dict]) -> None:
    def at(t: float) -> str:
        return f"{int(t // 60):02d}:{t % 60:06.3f}"
    lines = ["WEBVTT", ""]
    for c in cues:
        who = "You" if c["who"] == "you" else "Pointe"
        lines += [f"{at(c['t'])} --> {at(c['end'])}", f"<v {who}>{c['text']}", ""]
    (ROOT / "site" / "pointe" / "scenes" / f"{name}.vtt").write_text("\n".join(lines))


if __name__ == "__main__":
    name, footage, voices, cues = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), json.loads(Path(sys.argv[4]).read_text())
    work = Path(sys.argv[5]) if len(sys.argv) > 5 else Path(tempfile.mkdtemp(prefix="scene-film-"))
    captions(name, cues["cues"])
    for look in ("light", "dark"):
        n = len(list((work / look).glob("*.png"))) if "--encode" in sys.argv else (shutil.rmtree(work / look, ignore_errors=True), asyncio.run(frames(name, look, cues["total"], work / look)))[1]
        film(name, look, work, footage, voices, cues["total"])
        print(look, n, "frames", flush=True)
