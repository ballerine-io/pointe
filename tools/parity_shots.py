"""The page's side of the parity screenshots (docs/design/parity.md): the same invented call the apps' demo shows,
in headless Chrome against the page rig's stub Mac, at a desktop width and a phone width, light and dark.

    uv run --locked python tools/parity_shots.py [out folder, default /tmp/parity-shots/web]
    uv run --locked python tools/parity_shots.py --side-by-side [folder with web/ ios/ mac/, default /tmp/parity-shots]

The iPhone's come from the simulator (`-demo <screen>`) and the Mac's from the built app with the same argument; see
"Screenshots" in docs/design/parity.md. Invented names only; nothing is fetched from anywhere.
"""

import asyncio
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import page_rig  # noqa: E402

# ios Demo.swift: the call the apps' `-demo request` shows
SESSIONS = [
    {"name": "billing/main", "working": False, "waiting": True, "needs": None, "harness": "claude-code", "request_id": "r1",
     "request": "git push --force-with-lease origin retry-fix", "voice_can_approve": True, "capabilities": {"approvals": True}, "online": True},
    {"name": "docs", "working": False, "waiting": False, "needs": None, "harness": "claude-code", "capabilities": {"approvals": True}, "online": True},
]
TALK = [
    {"id": 40, "who": "user", "text": "what's billing doing", "typed": False, "corrected": False, "understood": "What is the billing session doing?"},
    {"id": 41, "who": "assistant", "text": "It finished the retry fix. Tests pass. It wants to know if it should open the PR."},
    {"id": 42, "who": "user", "text": "yes and tell docs to update the change log", "typed": False, "corrected": False,
     "understood": "Yes. And tell docs to update the changelog."},
    {"id": 43, "who": "assistant", "text": "Docs is on it. Billing is opening the PR."},
    {"id": 44, "who": "user", "text": "by the way why did billing drop the queue idea", "typed": True, "corrected": False},
    {"id": 45, "who": "assistant", "text": "Duplicate charges during failover. It decided that an hour ago."},
    {"id": 46, "who": "user", "text": "tell building to bump the timeout to 30 seconds", "typed": False, "corrected": True,
     "understood": "Tell billing to raise the timeout to 30 seconds."},
]

SIZES = {"desktop": (1280, 800, 2), "phone": (402, 874, 3)}


# The screens the iPhone's ParityUITests shoots, by the page's name for them: (iPhone shot, Settings section or None).
# Settings sections open the sheet and jump there, as the iPhone's Settings list does.
SCENES = {"request": ("request", None), "call": ("call", None), "settings": ("settings", ""),
          "machines": ("machines-all", None), "settings-machines": ("settings-machines", "machines"),
          "settings-keys": ("settings-keys", "g-keys"), "settings-approvals": ("settings-approvals", "g-approvals"),
          "settings-appearance": ("settings-appearance", "g-appearance"), "settings-local": ("settings-local", "g-local"),
          "settings-agents": ("settings-agents", "agents")}


def scene(name: str) -> dict:
    status = page_rig.fixture(sessions=0, connected=True)
    status.update({"active": "billing/main", "connected": True, "mode": "orchestrator", "sessions": [dict(s) for s in SESSIONS], "talk": TALK,
                   "version": "1.17.0"})
    if name == "machines":  # three machines, as the apps' `-demo machines`
        status = page_rig.fixture(sessions=6, machines=3, connected=True, talk=4)
    elif name != "request":
        for s in status["sessions"]:
            s.update(waiting=False, request=None, request_id=None, working=s["name"] == "billing/main")
    return status


async def shoot(out: Path, scenes: list[str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    stub = await page_rig.StubMac().start()
    try:
        for name in scenes:
            stub.status = scene(name)
            for size, (width, height, scale) in SIZES.items():
                for look in ("light", "dark"):
                    async with page_rig.Browser() as browser:
                        page = await browser.open(stub.url)
                        await page.cdp("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": scale,
                                                                              "mobile": size == "phone"})
                        await page.cdp("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": look}]})
                        await page.cdp("Page.reload")
                        await asyncio.sleep(0.5)
                        await page.wait_for_page()
                        section = SCENES[name][1]
                        if section is not None:
                            await page.eval("(async () => { await openSettings(); return true; })()")
                            if section:
                                await page.eval(f"settingsJump({section!r}); true")
                        await stub.polled(2)
                        await asyncio.sleep(0.5)  # a sheet's slide-in, which no poll marks
                        shot = await page.cdp("Page.captureScreenshot", {"format": "png"})
                        path = out / f"{name}-{size}-{look}.png"
                        path.write_bytes(base64.b64decode(shot["data"]))
                        print(path)
    finally:
        await stub.stop()


def side_by_side(root: Path) -> None:
    """One image per screen and appearance: the page, the iPhone and the Mac beside each other, at one height.
    `root` holds web/, ios/ and mac/ (the names this script and macos/e2e/smoke.py write, and `<screen>-<look>.png`
    from the simulator)."""
    from PIL import Image

    pairs = {name: (f"{name}-desktop", ios, "sheet-settings" if name == "settings" else name) for name, (ios, _) in SCENES.items()}
    for screen, (web, ios, mac) in pairs.items():
        for look in ("light", "dark"):
            files = [root / "web" / f"{web}-{look}.png", root / "ios" / f"{ios}-{look}.png", root / "mac" / f"{mac}-{look}.png"]
            if not all(f.exists() for f in files):
                continue
            images = [Image.open(f).convert("RGB") for f in files]
            height = 1400
            images = [im.resize((round(im.width * height / im.height), height)) for im in images]
            sheet = Image.new("RGB", (sum(im.width for im in images) + 40 * (len(images) + 1), height + 80), "#FFFFFF" if look == "light" else "#0A0400")
            x = 40
            for im in images:
                sheet.paste(im, (x, 40))
                x += im.width + 40
            out = root / f"side-by-side-{screen}-{look}.png"
            sheet.save(out)
            print(out)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--side-by-side" in sys.argv:
        side_by_side(Path(args[0]) if args else Path("/tmp/parity-shots"))
    else:
        asyncio.run(shoot(Path(args[0]) if args else Path("/tmp/parity-shots/web"), list(SCENES)))
