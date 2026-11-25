"""tools/ui_guard.py: a script that opens windows on the Mac (the Mac smoke, the XCUITests, the iPhone UI tests in the
Simulator) refuses to start on a person's Mac unless CI=true or POINTE_UI_LOCAL=1. Nothing here builds or opens
anything: each script is started with an empty PATH, so one that got past the guard could find no compiler, no
xcodebuild and no simulator, and would fail the test instead of taking the screen."""

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ui_guard", ROOT / "tools" / "ui_guard.py")
ui_guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui_guard)

# What marks a script as one that starts a UI test: xcodebuild's test selection, a prebuilt test run, or the
# Accessibility driver.
STARTS_UI = re.compile(r"only-testing|test-without-building|xctestrun|axdrive")
# Started with no arguments and nothing on PATH, each of these reaches its guard before anything else.
DRIVERS = sorted(str(p.relative_to(ROOT)) for p in [*(ROOT / "apps" / "ios" / "e2e").glob("*.py"), ROOT / "tests" / "e2e" / "ios_app.py",
                                                    ROOT / "tests" / "e2e" / "ios_phone_pair.py", ROOT / "apps" / "macos" / "e2e" / "smoke.py"]
                 if "ui_guard" in p.read_text())


def run(argv: list[str], tmp_path: Path, **env: str) -> subprocess.CompletedProcess:
    empty = tmp_path / "no-tools"
    empty.mkdir(exist_ok=True)
    return subprocess.run(argv, capture_output=True, text=True, timeout=60, cwd=ROOT, stdin=subprocess.DEVNULL,
                          env={"PATH": str(empty), "HOME": str(tmp_path), "POINTE_SMOKE_APP": "/nonexistent/build/Pointe.app", **env})


def test_only_ci_or_the_persons_own_word_lets_a_ui_test_run():
    assert ui_guard.allowed({"CI": "true"})
    assert ui_guard.allowed({"POINTE_UI_LOCAL": "1"})
    assert not ui_guard.allowed({})
    assert not ui_guard.allowed({"CI": "false", "POINTE_UI_LOCAL": "0"})
    assert not ui_guard.allowed({"CI": "", "POINTE_UI_LOCAL": ""})


def test_the_refusal_is_one_line_that_says_why_and_how_to_run_it_in_ci():
    line = ui_guard.refusal("apps/macos/e2e/smoke.py")
    assert "\n" not in line
    assert "apps/macos/e2e/smoke.py" in line and "keyboard" in line
    assert f"gh workflow run {ui_guard.WORKFLOW}" in line and "POINTE_UI_LOCAL=1" in line


def test_every_script_that_starts_a_ui_test_calls_the_guard():
    scripts = [p for top in ("apps", "tests/e2e", "tools", "bin") for p in (ROOT / top).rglob("*") if p.suffix in (".py", ".sh") and p.is_file()
               and "/build/" not in str(p) and p.name != "ui_guard.py"]
    starters = sorted(str(p.relative_to(ROOT)) for p in scripts if STARTS_UI.search(p.read_text(errors="ignore")))
    assert "apps/macos/e2e/smoke.py" in starters and "apps/macos/test.sh" in starters and len(starters) >= 15, starters
    assert [s for s in starters if "ui_guard.py" not in (ROOT / s).read_text()] == []


@pytest.mark.parametrize("script", DRIVERS)
def test_a_driver_refuses_before_it_reads_an_argument_or_builds(script, tmp_path):
    done = run([sys.executable, "-I", script], tmp_path)
    assert done.returncode == 2, done.stderr[-400:]
    assert done.stderr.strip() == ui_guard.refusal(script) and done.stdout == ""


def test_the_drivers_are_all_here():
    assert len(DRIVERS) == 12 and "apps/macos/e2e/smoke.py" in DRIVERS, DRIVERS


@pytest.mark.parametrize("script", ["apps/macos/e2e/smoke.py", "apps/macos/e2e/live.py"])
def test_the_guard_is_the_first_thing_main_does(script):
    """live.py starts a daemon and the app; it is checked by reading it, never by running it."""
    body = (ROOT / script).read_text().split("def main() -> int:\n", 1)[1]
    assert body.lstrip().startswith('runpy.run_path(str(ROOT / "tools" / "ui_guard.py"))["require"](')


def test_the_demo_recording_asks_before_it_touches_the_simulator():
    text = (ROOT / "tools" / "demo-video" / "capture.py").read_text()
    assert text.index('ui_guard.py"))["require"](') < text.index('"simctl", "list", "devices", "booted"')


@pytest.mark.parametrize("env", [{"CI": "true"}, {"POINTE_UI_LOCAL": "1"}])
def test_the_command_form_lets_an_allowed_run_through(env, tmp_path):
    done = run([sys.executable, "-I", "tools/ui_guard.py", "a UI test"], tmp_path, **env)
    assert done.returncode == 0 and done.stderr == ""


@pytest.mark.parametrize("what", ["ui", "smoke", "all"])
def test_test_sh_refuses_its_ui_parts(what, tmp_path):
    """PATH holds dirname and python3 only: past the guard there is no xcodebuild, no swift and no caffeinate to find."""
    tools = tmp_path / "bin"
    tools.mkdir()
    for name in ("dirname", "python3"):
        os.symlink(shutil.which(name), tools / name)
    done = subprocess.run([shutil.which("bash"), "apps/macos/test.sh", what], capture_output=True, text=True, timeout=60, cwd=ROOT,
                          stdin=subprocess.DEVNULL, env={"PATH": str(tools), "HOME": str(tmp_path)})
    assert done.returncode == 2, done.stderr[-400:]
    assert done.stderr.startswith(f"refused: apps/macos/test.sh {what} ") and done.stderr.count("\n") == 1


def test_test_sh_unit_is_not_a_ui_test():
    text = (ROOT / "apps" / "macos" / "test.sh").read_text()
    assert 'if [ "$WHAT" != unit ]; then\n  python3 -I ../../tools/ui_guard.py' in text
    assert text.index("ui_guard.py") < text.index("&& swift test")
