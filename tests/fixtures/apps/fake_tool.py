#!/usr/bin/env python3
"""One stand-in for every Apple tool apps.py runs (tests/test_apps.py links it under each tool's name). It answers from
the fixtures beside it, or from the file an environment variable names, and appends each call to $FAKE_LOG."""
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(os.path.realpath(__file__)).parent
name, argv = Path(sys.argv[0]).name, sys.argv[1:]
env = os.environ


def fixture(variable: str, default: str) -> str:
    return (HERE / env.get(variable, default)).read_text()


def after(flag: str) -> str:
    return argv[argv.index(flag) + 1]


with open(env["FAKE_LOG"], "a") as log:
    log.write(json.dumps([name] + argv) + "\n")

if name == "xcode-select":
    print(env.get("FAKE_XCODE_PATH", "/Applications/Xcode.app/Contents/Developer"))
elif name == "sw_vers":
    print("15.1")
elif name == "security":
    print(fixture("FAKE_IDENTITIES", "find_identity_one.txt") if argv[0] == "find-identity" else fixture("FAKE_CERTIFICATES", "certificate_one_team.pem"), end="")
elif name == "xcodebuild":
    if argv[0] == "-version":
        print(fixture("FAKE_XCODE_VERSION", "xcodebuild_version.txt"), end="")
        sys.exit(1 if "FAKE_XCODE_VERSION" in env else 0)
    if argv[0] == "build":
        signed = any(a.startswith("DEVELOPMENT_TEAM=") and len(a) > 17 for a in argv)
        only = env.get("FAKE_BUILD_ERROR_IF")  # fail only the builds with this argument
        if "FAKE_BUILD_ERROR" in env and (signed or env.get("FAKE_BUILD_ERROR_ALWAYS")) and (not only or only in argv):
            print(fixture("FAKE_BUILD_ERROR", ""), end="")
            sys.exit(65)
        destination, configuration = after("-destination"), after("-configuration")
        folder = configuration if "macOS" in destination else configuration + ("-iphoneos" if "TEAM" in " ".join(argv) else "-iphonesimulator")
        app = Path(after("-derivedDataPath")) / "Build" / "Products" / folder / "Pointe.app"
        (app / "Contents" / "MacOS").mkdir(parents=True, exist_ok=True)
        (app / "Contents" / "MacOS" / "Pointe").write_text(" ".join(argv))
        if "FAKE_PROFILE" in env:
            shutil.copy(env["FAKE_PROFILE"], app / "embedded.mobileprovision")
elif name == "xcrun" and argv[:3] == ["devicectl", "list", "devices"]:
    shutil.copy(env.get("FAKE_DEVICES", HERE / "devices.json"), after("--json-output"))
elif name == "xcrun" and argv[:4] == ["devicectl", "device", "install", "app"] and "FAKE_INSTALL_ERROR" in env:
    print(fixture("FAKE_INSTALL_ERROR", ""), end="")
    sys.exit(1)
elif name == "xcrun" and argv[:4] == ["devicectl", "device", "process", "launch"] and "FAKE_LAUNCH_ERROR" in env:
    print(fixture("FAKE_LAUNCH_ERROR", ""), end="")
    sys.exit(1)
elif name == "xcrun" and argv[:3] == ["simctl", "list", "devices"]:
    print(fixture("FAKE_SIMULATORS", "simctl_devices.json"))
elif name == "ditto":
    shutil.copytree(argv[0], argv[1])
elif name == "pgrep":
    running = Path(env.get("FAKE_RUNNING", "/nonexistent"))
    if not running.exists():
        sys.exit(1)
    print("4242")
elif name == "kill":
    Path(env["FAKE_RUNNING"]).unlink()
