"""The iPhone app pairs from the page's QR link, opened by the system as the Camera app opens it: a test daemon, a
one-time code made through the page's own route (its cookie), and ios/PointeUITests/PairByLinkUITests.swift, which opens
the link, sees "Paired with <Mac>", and sees the same link refused a second time. Then the daemon lists the phone, and
the phone shows online because the app polls with the key it was given.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-pc2 CLAUDE_VOICE_DAEMON_PORT=7971 CLAUDE_VOICE_TLS_PORT=7571 POINTE_SHOTS=/tmp/pc-shots \
     DEVELOPMENT_TEAM="$(cat ios/.team)" uv run python -u -I tests/e2e/ios_phone_pair.py "PC iPhone"
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rig import DAEMON, ROOT, STATE, fresh_state, stop_daemon  # noqa: E402

assert os.environ.get("CLAUDE_VOICE_STATE") and os.environ.get("CLAUDE_VOICE_TLS_PORT"), "isolated state and TLS port"
SIMULATOR = sys.argv[1]
NAME = "pointe.localtest.me"  # a real name: iOS exempts localhost from App Transport Security, which would hide a refusal
SHOTS = Path(os.environ.get("POINTE_SHOTS", "/tmp/pc-shots"))
results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, **detail) -> None:
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {json.dumps(detail)[:300]}", flush=True)


def as_page(method: str, path: str, body: dict | None = None) -> dict:
    """The page's own request: its cookie, from this Mac."""
    request = urllib.request.Request(f"{DAEMON}{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"cookie": f"pointe_local={(STATE / 'page_key').read_text().strip()}",
                                              "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=30).read())


def with_token(path: str) -> dict:
    request = urllib.request.Request(f"{DAEMON}{path}", headers={"Authorization": f"Bearer {(STATE / 'token').read_text().strip()}"})
    return json.loads(urllib.request.urlopen(request, timeout=10).read())


def main() -> None:
    fresh_state()
    for name in ("remote.json", "remote_token", "phone_key", "phones.json"):
        (STATE / name).unlink(missing_ok=True)
    shutil.rmtree(STATE / "tls", ignore_errors=True)
    import hub_nodes
    import pair

    pair.STATE = STATE
    pair.setup(NAME, "127.0.0.1")  # set up before, as `pointe pair host` would: the page keeps this route
    config = json.loads((STATE / "remote.json").read_text())
    (STATE / "remote.json").write_text(json.dumps({**config, "listen": ["127.0.0.1", "::1"]}))  # the name resolves to either
    up = subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, text=True, env=dict(os.environ))
    assert up.returncode == 0, up.stderr[-400:]

    made = as_page("POST", "/voice/phone/invite", {"kind": "host", "host": NAME})
    check("the page's route made a code link for the route set up before", made["link"].startswith("pointe://pair?v=2&host=pointe.localtest.me"),
          host=made["host"])
    mac = hub_nodes._here(STATE)

    SHOTS.mkdir(parents=True, exist_ok=True)
    bundle = SHOTS / "ios-pair.xcresult"
    shutil.rmtree(bundle, ignore_errors=True)
    subprocess.run(["xcrun", "simctl", "boot", SIMULATOR], capture_output=True)
    test = subprocess.run(
        ["xcodebuild", "-project", str(ROOT / "ios" / "Pointe.xcodeproj"), "-scheme", "Pointe",
         "-destination", f"platform=iOS Simulator,name={SIMULATOR}", "-derivedDataPath", os.environ.get("POINTE_DERIVED_DATA", "/tmp/dd-pc"),
         "-only-testing:PointeUITests/PairByLinkUITests", "-resultBundlePath", str(bundle),
         *([f"DEVELOPMENT_TEAM={os.environ['DEVELOPMENT_TEAM']}"] if os.environ.get("DEVELOPMENT_TEAM") else []), "test"],
        env={**os.environ, "TEST_RUNNER_POINTE_PAIR_CODE_LINK": made["link"], "TEST_RUNNER_POINTE_PAIR_MAC": mac},
        capture_output=True, text=True)
    tail = [l for l in test.stdout.splitlines() if "error" in l or "passed" in l or "failed" in l or "skipped" in l][-8:]
    check("the UI test: the system-opened link pairs, says so, and is refused a second time",
          test.returncode == 0 and "skipped" not in test.stdout.lower().split("** test")[0][-2000:], tail=tail)

    try:
        out = SHOTS / "ios"
        shutil.rmtree(out, ignore_errors=True)
        subprocess.run(["xcrun", "xcresulttool", "export", "attachments", "--path", str(bundle), "--output-path", str(out)],
                       capture_output=True, timeout=60)
        manifest = json.loads((out / "manifest.json").read_text())
        for test_case in manifest:
            for a in test_case.get("attachments", []):
                (out / a["exportedFileName"]).rename(out / f"pair-{a['suggestedHumanReadableName'].split('_')[0]}.png")
    except (OSError, ValueError, subprocess.SubprocessError, KeyError) as e:
        print(f"  (screenshots not exported: {e})")

    invite = as_page("GET", "/voice/phone/invite")
    check("the page sees who paired", bool(invite["paired"] and invite["paired"]["name"]), paired=invite["paired"])
    deadline, phones = time.time() + 20, {}
    while time.time() < deadline:
        phones = with_token("/voice/status")["phones"]
        if any(p["last_seen"] for p in phones["paired"]):
            break
        time.sleep(1)
    entry = next((p for p in phones["paired"] if not p["legacy"]), {})
    check("the daemon lists the phone, seen with a key of its own", bool(entry.get("last_seen")) and not (STATE / "phone_key").exists(),
          phones=phones)
    stop_daemon()
    print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed (ios phone pair)")
    sys.exit(0 if all(ok for _, ok in results) else 1)


if __name__ == "__main__":
    main()
