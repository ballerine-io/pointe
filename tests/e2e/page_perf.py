"""How responsive the page is, in numbers: the page in a headless Chrome against a stub Mac (tests/page_rig.py).

    uv run python -u -I tests/e2e/page_perf.py --out /tmp/page-perf/before.json [--port 7997] [--quick]
    uv run python -u -I tests/e2e/page_perf.py --compare /tmp/page-perf/before.json /tmp/page-perf/after.json

Two fixtures (one session; 20 sessions on 3 machines, 200 talk lines, one approval waiting), each at 1x and 4x CPU
throttle. For each: 10 s idle (long tasks, style and layout counts, script time, the render time of each poll, DOM
mutations in the lists, composited frames and paint from a trace), click-to-visible-change for the controls the owner
uses, the same with the Mac stalled 1.5 s, a press that spans a poll, and 3 s of wheel scrolling over the talk list.
No daemon, no network beyond the stub: the numbers are the page's own.
"""

import argparse
import asyncio
import base64
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from page_rig import PROBES, ROOT, Browser, StubMac, fixture  # noqa: E402

TRACE_CATEGORIES = ["devtools.timeline", "disabled-by-default-devtools.timeline", "disabled-by-default-devtools.timeline.frame"]
TRACE_SUMS = ["FunctionCall", "TimerFire", "EventDispatch", "UpdateLayoutTree", "Layout", "PrePaint", "Paint", "RasterTask",
              "UpdateLayerTree", "UpdateLayer", "CompositeLayers", "Commit", "HitTest", "MinorGC", "MajorGC", "Animation"]
TRACE_COUNTS = ["DrawFrame", "BeginMainThreadFrame", "Paint", "Layout", "UpdateLayoutTree", "RasterTask"]

# Each click: the control, and what "visibly changed" means for it.
CLICKS = {
    "focus_session": """(() => { const rows = [...document.querySelectorAll('#list .s')]; const b = rows[Math.min(4, rows.length - 1)];
        const name = b.title.split(' ')[0].replace(/:$/, ''); const t0 = performance.now(); b.click();
        return __until(() => [...document.querySelectorAll('#list .s.on')].some(x => x.title.split(' ')[0].replace(/:$/, '') === name)); })()""",
    "orchestrator_mode": """(() => { document.getElementById('m-orchestrator').click();
        return __until(() => document.getElementById('m-orchestrator').className === 'on'); })()""",
    "open_settings": """(() => { document.getElementById('settingsbtn').click();
        return __until(() => document.getElementById('settingssheet').classList.contains('open')); })()""",
    "toggle_switch": """(() => { const b = document.getElementById('pref-lookups'); const was = b.checked; b.click();
        return __until(() => b.checked !== was); })()""",
    "close_settings": """(() => { closeSheet('settingssheet'); return __until(() => !document.getElementById('settingssheet').classList.contains('open')); })()""",
    "mic_connect": """(() => { document.getElementById('mic').click(); return __until(() => document.body.dataset.state !== 'off'); })()""",
    "hang_up": """(() => { endCall(); return __until(() => document.body.dataset.state === 'off'); })()""",
    "hold_to_talk_on": """(() => { document.getElementById('micmode-ptt').click();
        return __until(() => document.getElementById('micmode-ptt').classList.contains('on')); })()""",
    "hold_to_talk_off": """(() => { document.getElementById('micmode-always').click();
        return __until(() => document.getElementById('micmode-always').classList.contains('on')); })()""",
}


def metrics(r: dict) -> dict:
    return {m["name"]: m["value"] for m in r["metrics"]}


def delta(a: dict, b: dict) -> dict:
    keys = ["LayoutCount", "RecalcStyleCount", "LayoutDuration", "RecalcStyleDuration", "ScriptDuration", "TaskDuration", "Nodes"]
    out = {k: round(b[k] - a[k], 4) for k in keys if k in a and k in b}
    out["Nodes"] = b.get("Nodes")
    return out


def summarize(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    values = sorted(values)
    return {"n": len(values), "mean": round(statistics.fmean(values), 2), "p95": round(values[int(len(values) * 0.95) - 1 if len(values) > 1 else 0], 2),
            "max": round(values[-1], 2)}


async def stop_tracing(page) -> dict:
    done = asyncio.Event()
    handle = {}

    def cb(msg):
        if msg.get("method") == "Tracing.tracingComplete":
            handle["h"] = msg["params"].get("stream")
            done.set()

    page.on(cb)
    await page.cdp("Tracing.end")
    await asyncio.wait_for(done.wait(), 30)
    page.listeners.remove(cb)
    chunks = []
    while True:
        r = await page.cdp("IO.read", {"handle": handle["h"], "size": 1 << 22})
        chunks.append(base64.b64decode(r["data"]).decode() if r.get("base64Encoded") else r["data"])
        if r.get("eof"):
            break
    await page.cdp("IO.close", {"handle": handle["h"]})
    events = json.loads("".join(chunks))
    events = events.get("traceEvents", events) if isinstance(events, dict) else events
    sums = {k: 0.0 for k in TRACE_SUMS}
    counts = {k: 0 for k in TRACE_COUNTS}
    for e in events:
        name = e.get("name")
        if name in sums and e.get("ph") == "X":
            sums[name] += e.get("dur", 0) / 1000
        if name in counts and e.get("ph") in ("X", "I", "i", "b"):
            counts[name] += 1
    return {"ms": {k: round(v, 1) for k, v in sums.items() if v}, "count": {k: v for k, v in counts.items() if v}, "events": len(events)}


async def idle_window(page, secs: float, css: str = "") -> dict:
    """What the page does on its own for `secs`, with nothing happening; `css` is injected first (an A/B)."""
    sid = None
    if css:
        await page.cdp("DOM.enable")
        await page.cdp("CSS.enable")
        sid = (await page.cdp("CSS.createStyleSheet", {"frameId": await frame_id(page)}))["styleSheetId"]
        await page.cdp("CSS.setStyleSheetText", {"styleSheetId": sid, "text": css})
        await asyncio.sleep(0.5)
    await page.eval("__reset()")
    m0 = metrics(await page.cdp("Performance.getMetrics"))
    await page.cdp("Tracing.start", {"traceConfig": {"includedCategories": TRACE_CATEGORIES}, "transferMode": "ReturnAsStream"})
    t0 = time.monotonic()
    await asyncio.sleep(secs)
    trace = await stop_tracing(page)
    m1 = metrics(await page.cdp("Performance.getMetrics"))
    probe = json.loads(await page.eval("JSON.stringify(__probe)"))
    if sid:
        await page.cdp("CSS.setStyleSheetText", {"styleSheetId": sid, "text": ""})
    longs = [x["dur"] for x in probe["longtasks"]]
    return {"seconds": round(time.monotonic() - t0, 1), "metrics": delta(m0, m1),
            "longtasks": {"n": len(longs), "total_ms": round(sum(longs), 1), "max_ms": round(max(longs), 1) if longs else 0},
            "tick_render_ms": summarize(probe["ticks"]), "mutations": probe["muts"], "trace": trace}


async def frame_id(page) -> str:
    return (await page.cdp("Page.getFrameTree"))["frameTree"]["frame"]["id"]


async def clicks(page, names=CLICKS) -> dict:
    out = {}
    for name in names:
        out[name] = await page.eval(CLICKS[name])
        await asyncio.sleep(0.3)
    return out


async def press_spanning_a_poll(page, stub: StubMac) -> dict:
    """Mouse down on a session row, a poll lands, mouse up: does the row's click still arrive?"""
    x, y = await page.eval("(() => { const rows = document.querySelectorAll('#list .s'), r = rows[Math.min(2, rows.length - 1)].getBoundingClientRect();"
                           " return [r.x + 40, r.y + r.height / 2]; })()")
    stub.posts.clear()
    await page.cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    await page.cdp("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
    await page.eval("(async () => { while (inflight) await new Promise(r => setTimeout(r, 20)); await refresh(); return true; })()")
    await page.cdp("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})
    await asyncio.sleep(0.6)
    delivered = any(p[0] == "/voice/switch" for p in stub.posts)
    stub.status["mode"], stub.status["active"] = "orchestrator", stub.status["sessions"][0]["name"]
    return {"delivered": delivered}


async def wheel_scroll(page, secs: float = 3.0) -> dict:
    x, y = await page.eval("(() => { const r = document.getElementById('talk').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
    await page.eval("__reset()")
    m0 = metrics(await page.cdp("Performance.getMetrics"))
    t0 = time.monotonic()
    i = 0
    while time.monotonic() - t0 < secs:
        dy = -120 if (i // 20) % 2 == 0 else 120
        await page.cdp("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": dy})
        await asyncio.sleep(0.05)
        i += 1
    m1 = metrics(await page.cdp("Performance.getMetrics"))
    probe = json.loads(await page.eval("JSON.stringify(__probe)"))
    longs = [t["dur"] for t in probe["longtasks"]]
    return {"wheel_events": i, "metrics": delta(m0, m1), "longtasks": {"n": len(longs), "total_ms": round(sum(longs), 1)}}


async def scenario(name: str, status: dict, throttle: int, port: int, quick: bool, ab: bool) -> dict:
    stub = await StubMac(port).start()
    stub.status = status
    out = {"throttle": throttle}
    try:
        async with Browser() as browser:
            page = await browser.open(stub.url)
            await page.cdp("Performance.enable")
            if throttle > 1:
                await page.cdp("Emulation.setCPUThrottlingRate", {"rate": throttle})
            await page.eval(PROBES)
            await asyncio.sleep(1.5)
            idle = 4 if quick else 10
            out["idle"] = await idle_window(page, idle)
            if ab:
                out["idle_no_blur"] = await idle_window(page, idle, ".dock, .top, .sheetbg { backdrop-filter: none !important; }")
                out["idle_no_animations"] = await idle_window(page, idle, "* { animation: none !important; }")
            out["clicks"] = await clicks(page)
            stub.delay = 1.5
            out["clicks_stalled"] = await clicks(page, [k for k in CLICKS if k not in ("mic_connect", "hang_up")])
            stub.delay = 0
            await asyncio.sleep(2)
            out["press_spanning_a_poll"] = await press_spanning_a_poll(page, stub)
            await asyncio.sleep(1)
            out["scroll"] = await wheel_scroll(page, 1.5 if quick else 3)
    finally:
        await stub.stop()
    print(f"  {name}@{throttle}x: idle longtasks {out['idle']['longtasks']}, tick {out['idle']['tick_render_ms']}, "
          f"mut {out['idle']['mutations']}, layouts {out['idle']['metrics'].get('LayoutCount')}", flush=True)
    return out


def head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except Exception:
        return "?"


async def main(args) -> None:
    fixtures = {"small": fixture(sessions=1), "big": fixture(sessions=20, machines=3, talk=200, approval=True)}
    result = {"when": time.strftime("%Y-%m-%d %H:%M:%S"), "git": head(), "scenarios": {}}
    for fname, status in fixtures.items():
        for throttle in ([1, 4] if not args.quick else [4]):
            key = f"{fname}@{throttle}x"
            print(key, flush=True)
            result["scenarios"][key] = await scenario(fname, json.loads(json.dumps(status)), throttle, args.port, args.quick,
                                                      ab=(fname == "big" and throttle == 1))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=1))
    print(f"wrote {args.out}")


def compare(before: Path, after: Path) -> None:
    a, b = json.loads(before.read_text()), json.loads(after.read_text())
    rows = []

    def pick(d, *path):
        for p in path:
            d = d.get(p, {}) if isinstance(d, dict) else {}
        return d if d != {} else None

    def fmt(v):
        if v is None:
            return "—"
        if isinstance(v, float):
            return f"{v:.1f}"
        if isinstance(v, dict) and "ms" in v:
            return "never" if v["ms"] is None else f"{v['ms']:.0f} ms / {v['frames']} f"
        if isinstance(v, dict) and "delivered" in v:
            return "yes" if v["delivered"] else "LOST"
        return str(v)

    for key in a["scenarios"]:
        if key not in b["scenarios"]:
            continue
        sa, sb = a["scenarios"][key], b["scenarios"][key]
        metricz = [
            ("idle 10 s: long tasks (n / total ms)", lambda s: f"{pick(s, 'idle', 'longtasks', 'n')} / {pick(s, 'idle', 'longtasks', 'total_ms')}"),
            ("idle 10 s: script ms", lambda s: round(1000 * (pick(s, "idle", "metrics", "ScriptDuration") or 0))),
            ("idle 10 s: layouts / style recalcs", lambda s: f"{pick(s, 'idle', 'metrics', 'LayoutCount')} / {pick(s, 'idle', 'metrics', 'RecalcStyleCount')}"),
            ("idle 10 s: layout ms + style ms", lambda s: round(1000 * ((pick(s, "idle", "metrics", "LayoutDuration") or 0) + (pick(s, "idle", "metrics", "RecalcStyleDuration") or 0)))),
            ("idle 10 s: paint ms / raster ms (trace)", lambda s: f"{pick(s, 'idle', 'trace', 'ms', 'Paint') or 0} / {pick(s, 'idle', 'trace', 'ms', 'RasterTask') or 0}"),
            ("idle 10 s: composited frames (trace)", lambda s: pick(s, "idle", "trace", "count", "DrawFrame") or 0),
            ("render ms per poll (mean / p95)", lambda s: f"{pick(s, 'idle', 'tick_render_ms', 'mean')} / {pick(s, 'idle', 'tick_render_ms', 'p95')}"),
            ("DOM mutations per 10 s: #list / #recent / #talk", lambda s: f"{pick(s, 'idle', 'mutations', 'list')} / {pick(s, 'idle', 'mutations', 'recent')} / {pick(s, 'idle', 'mutations', 'talk')}"),
            ("click → change: focus a session", lambda s: pick(s, "clicks", "focus_session")),
            ("click → change: Orchestrator mode", lambda s: pick(s, "clicks", "orchestrator_mode")),
            ("click → change: open Settings", lambda s: pick(s, "clicks", "open_settings")),
            ("click → change: toggle a switch", lambda s: pick(s, "clicks", "toggle_switch")),
            ("click → change: mic (connect)", lambda s: pick(s, "clicks", "mic_connect")),
            ("click → change: hold to talk", lambda s: pick(s, "clicks", "hold_to_talk_on")),
            ("Mac stalled 1.5 s: focus a session", lambda s: pick(s, "clicks_stalled", "focus_session")),
            ("Mac stalled 1.5 s: Orchestrator mode", lambda s: pick(s, "clicks_stalled", "orchestrator_mode")),
            ("Mac stalled 1.5 s: open Settings", lambda s: pick(s, "clicks_stalled", "open_settings")),
            ("Mac stalled 1.5 s: hold to talk", lambda s: pick(s, "clicks_stalled", "hold_to_talk_on")),
            ("a press that spans a poll", lambda s: pick(s, "press_spanning_a_poll")),
            ("3 s wheel scroll: long tasks / layouts", lambda s: f"{pick(s, 'scroll', 'longtasks', 'n')} / {pick(s, 'scroll', 'metrics', 'LayoutCount')}"),
        ]
        rows.append(f"\n**{key}**\n\n| metric | before | after |\n|---|---|---|")
        for label, f in metricz:
            rows.append(f"| {label} | {fmt(f(sa))} | {fmt(f(sb))} |")
        for ab in ("idle_no_blur", "idle_no_animations"):
            if ab in sa:
                rows.append(f"| A/B {ab}: paint / raster ms, frames | {fmt(f'{pick(sa, ab, 'trace', 'ms', 'Paint') or 0} / {pick(sa, ab, 'trace', 'ms', 'RasterTask') or 0}, {pick(sa, ab, 'trace', 'count', 'DrawFrame') or 0}')} "
                            f"| {fmt(f'{pick(sb, ab, 'trace', 'ms', 'Paint') or 0} / {pick(sb, ab, 'trace', 'ms', 'RasterTask') or 0}, {pick(sb, ab, 'trace', 'count', 'DrawFrame') or 0}') if ab in sb else '—'} |")
    print("\n".join(rows))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/page-perf/out.json")
    ap.add_argument("--port", type=int, default=7997)
    ap.add_argument("--quick", action="store_true", help="4 s idle windows, 4x only")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    a = ap.parse_args()
    if a.compare:
        compare(Path(a.compare[0]), Path(a.compare[1]))
    else:
        asyncio.run(main(a))
