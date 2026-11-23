"""`pointe apps` (apps.py, bin/pointe-apps): the iPhone and Mac apps built from source with one command.

The real script runs here against stand-ins for xcodebuild, xcrun, security and the rest (tests/fixtures/apps/
fake_tool.py), so this passes on Linux and builds nothing. The fixtures: the device list, the simulator list's shape,
`xcodebuild -version`, the identity listing's format and "No Accounts" are recorded from Xcode 27.2 with every name and
identifier replaced by an invented one; the other error texts are Apple's wording as Xcode and devicectl print it.
The certificates are self-signed and synthetic. No real Team ID, device or person is in any of them."""

import argparse
import datetime
import json
import os
import plistlib
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "apps"
TEAM, OTHER_TEAM = "ABCDE12345", "ZYXWV98765"
DERIVED = "io.ballerine.pointe.dev729e7a25"  # sha256("ABCDE12345")[:8]
TOOLS = ("xcode-select", "xcodebuild", "xcrun", "security", "sw_vers", "ditto", "pgrep", "kill", "open")

sys.path.insert(0, str(ROOT))
import apps  # noqa: E402


class Rig:
    """A throwaway home with the stand-in tools first on PATH. run() is the real bin/pointe-apps."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.bin.mkdir()
        for tool in TOOLS:
            (self.bin / tool).symlink_to(FIXTURES / "fake_tool.py")
        self.log = tmp / "calls.jsonl"
        self.log.touch()
        self.team_file = tmp / "repo" / "ios" / ".team"
        self.bundle_file = tmp / "repo" / "ios" / ".bundle-id"
        self.profiles = tmp / "profiles"
        self.profiles.mkdir()
        self.apps = tmp / "Applications"
        self.env = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp), "FAKE_LOG": str(self.log),
            "POINTE_TEAM_FILE": str(self.team_file), "POINTE_APPS_BUILD": str(tmp / "build"),
            "POINTE_APPS_PROFILES": str(self.profiles), "POINTE_APPS_INSTALL_DIR": str(self.apps),
        }

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run([str(ROOT / "bin" / "pointe-apps"), *args], env={**self.env, **env}, cwd=self.tmp,
                              capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)

    def calls(self, tool: str | None = None) -> list[list[str]]:
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [c for c in calls if tool in (None, c[0])]

    def builds(self) -> list[list[str]]:
        return [c for c in self.calls("xcodebuild") if c[1] == "build"]

    def devices(self, change) -> str:
        """The recorded device list with the one iPhone changed; returns the file for FAKE_DEVICES."""
        data = json.loads((FIXTURES / "devices.json").read_text())
        phones = [d for d in data["result"]["devices"] if d["hardwareProperties"]["reality"] == "physical"]
        if change is None:
            data["result"]["devices"] = [d for d in data["result"]["devices"] if d not in phones]
        else:
            change(phones[0])
        path = self.tmp / "devices.json"
        path.write_text(json.dumps(data))
        return str(path)

    def profile(self, team: str, bundle: str, days: int, where: Path | None = None) -> str:
        made = datetime.datetime(2026, 1, 1, 12, 0)
        body = plistlib.dumps({"Entitlements": {"application-identifier": f"{team}.{bundle}"}, "CreationDate": made,
                               "ExpirationDate": made + datetime.timedelta(days=days), "TeamIdentifier": [team]})
        path = (where or self.tmp) / "embedded.mobileprovision"
        path.write_bytes(b"\x30\x82 signed envelope " + body + b" signature bytes")
        return str(path)


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def setting(build: list[str], name: str) -> str | None:
    return next((a.split("=", 1)[1] for a in build if a.startswith(name + "=")), None)


# ---------- the team and the bundle ID ----------

def test_the_team_is_the_certificates_organizational_unit_not_the_id_in_its_name():
    teams = apps.teams_from_pem((FIXTURES / "certificates_two_teams.pem").read_text())
    assert teams == {TEAM: "Dana Example", OTHER_TEAM: "Example Robotics Ltd"}  # AAAAAAAAAA, in the name, is the person


def test_one_team_is_picked_saved_and_never_printed(rig):
    got = rig.run("ios", "--no-launch")
    assert got.returncode == 0, got.stdout + got.stderr
    assert rig.team_file.read_text().strip() == TEAM and oct(rig.team_file.stat().st_mode)[-3:] == "600"
    assert TEAM not in got.stdout + got.stderr and "your team" in got.stdout
    assert setting(rig.builds()[0], "DEVELOPMENT_TEAM") == TEAM


def test_a_team_that_does_not_own_the_published_id_gets_one_of_its_own(rig):
    """Apple gives a bundle ID to one team: a Personal Team cannot sign io.ballerine.pointe."""
    got = rig.run("ios", "--no-launch")
    build = rig.builds()[0]
    assert setting(build, "PRODUCT_BUNDLE_IDENTIFIER") == DERIVED == apps.derived_bundle_id(TEAM)
    assert rig.bundle_file.read_text().strip() == DERIVED and DERIVED in got.stdout
    assert {"-allowProvisioningUpdates", "-allowProvisioningDeviceRegistration", "CODE_SIGN_STYLE=Automatic"} <= set(build)
    assert apps.derived_bundle_id(OTHER_TEAM) != DERIVED


def test_the_team_that_owns_the_published_id_keeps_it(rig):
    """Only the owning team has a profile for io.ballerine.pointe; a wildcard or another team's profile does not count."""
    rig.profile(OTHER_TEAM, "io.ballerine.pointe", 7, rig.profiles)
    assert rig.run("ios", "--dry-run").stdout.count(DERIVED) == 2
    rig.profile(TEAM, "io.ballerine.pointe", 7, rig.profiles)
    rig.run("ios", "--no-launch")
    assert setting(rig.builds()[0], "PRODUCT_BUNDLE_IDENTIFIER") == "io.ballerine.pointe"


def test_the_saved_bundle_id_is_used_again_so_a_rebuild_updates_the_same_app(rig):
    rig.run("ios", "--no-launch", "--bundle-id", "com.example.pointe")
    rig.run("ios", "--no-launch")
    assert [setting(b, "PRODUCT_BUNDLE_IDENTIFIER") for b in rig.builds()] == ["com.example.pointe"] * 2


def test_changing_the_team_drops_the_bundle_id_of_the_old_team(rig):
    rig.run("ios", "--no-launch")
    rig.run("ios", "--no-launch", "--team", OTHER_TEAM)
    assert rig.team_file.read_text().strip() == OTHER_TEAM
    assert setting(rig.builds()[1], "PRODUCT_BUNDLE_IDENTIFIER") == apps.derived_bundle_id(OTHER_TEAM)


def test_two_teams_and_no_terminal_asks_for_a_choice_without_printing_an_id(rig):
    got = rig.run("ios", FAKE_IDENTITIES="find_identity_two.txt", FAKE_CERTIFICATES="certificates_two_teams.pem")
    assert got.returncode == 1 and "Example Robotics Ltd" in got.stdout and "--team" in got.stdout
    assert TEAM not in got.stdout and OTHER_TEAM not in got.stdout and not rig.builds()


def test_no_certificate_says_how_to_make_one_in_xcode(rig):
    got = rig.run("ios", FAKE_IDENTITIES="find_identity_none.txt")
    assert got.returncode == 1 and "Manage Certificates" in got.stdout and "ios --sim" in got.stdout and not rig.builds()


def test_a_bad_team_or_bundle_id_is_refused(rig):
    assert rig.run("ios", "--team", "not-a-team").returncode == 1 and not rig.team_file.exists()
    assert rig.run("ios", "--bundle-id", "no dots").returncode == 1
    assert not rig.bundle_file.exists() and not rig.builds()


def test_a_dry_run_shows_the_command_and_saves_and_builds_nothing(rig):
    got = rig.run("ios", "--dry-run")
    assert got.returncode == 0 and "DEVELOPMENT_TEAM=<your team>" in got.stdout and f"PRODUCT_BUNDLE_IDENTIFIER={DERIVED}" in got.stdout
    assert TEAM not in got.stdout and not rig.team_file.exists() and not rig.bundle_file.exists() and not rig.builds()
    for args in (("mac", "--dry-run"), ("ios", "--sim", "--dry-run")):
        got = rig.run(*args)
        assert got.returncode == 0 and "$ xcodebuild build" in got.stdout and TEAM not in got.stdout
    assert not rig.builds() and not (rig.tmp / "build").exists() and not rig.apps.exists()


def test_the_test_targets_are_not_part_of_what_the_command_builds():
    """PRODUCT_BUNDLE_IDENTIFIER on the command line reaches every target that is built: the schemes build only the app
    for running, so the test bundles (…tests, …uitests) keep their committed IDs and are built only by `xcodebuild test`."""
    for scheme in ("ios/Pointe.xcodeproj/xcshareddata/xcschemes/Pointe.xcscheme", "macos/PointeMac.xcodeproj/xcshareddata/xcschemes/PointeMac.xcscheme"):
        text = (ROOT / scheme).read_text()
        entries = text.split("<BuildAction", 1)[1].split("</BuildAction>", 1)[0]
        assert entries.count("<BuildActionEntry") == 1 and "Tests" not in entries, scheme


# ---------- the iPhone ----------

def test_ios_builds_for_the_iphone_installs_and_opens_the_app(rig):
    got = rig.run("ios", FAKE_PROFILE=rig.profile(TEAM, DERIVED, 7))
    assert got.returncode == 0, got.stdout
    build = rig.builds()[0]
    assert build[build.index("-destination") + 1] == "id=00008140-000A11112222001C" and "Release" in build
    devicectl = [c[1:] for c in rig.calls("xcrun") if c[1] == "devicectl" and c[2] == "device"]
    assert devicectl[0][:5] == ["devicectl", "device", "install", "app", "--device"] and devicectl[0][-1].endswith("Release-iphoneos/Pointe.app")
    assert devicectl[1][-1] == DERIVED and "process" in devicectl[1]
    assert "Dana's iPhone" in got.stdout and "7 days" in got.stdout and "Free Apple Account" in got.stdout


def test_a_paid_teams_profile_is_not_called_a_seven_day_one(rig):
    got = rig.run("ios", "--no-launch", FAKE_PROFILE=rig.profile(TEAM, DERIVED, 365))
    assert "Free Apple Account" not in got.stdout and "opens until" in got.stdout


@pytest.mark.parametrize("change, words", [
    (None, "No iPhone found"),
    (lambda d: (d["properties"]["connection"].update(state="unavailable"), d["connectionProperties"].update(tunnelState="unavailable")), "same Wi-Fi"),
    (lambda d: (d["properties"]["connection"].update(pairingState="unpaired"), d["connectionProperties"].update(pairingState="unpaired")), "Trust This Computer"),
    (lambda d: (d["properties"]["state"].update(developerModeStatus={"disabled": {}}), d["deviceProperties"].update(developerModeStatus="disabled")), "Privacy & Security, Developer Mode"),
    (lambda d: (d["properties"]["software"]["osVersionNumber"].update(stringValue="17.6"), d["deviceProperties"].update(osVersionNumber="17.6")), "needs iOS 18"),
])
def test_an_iphone_that_is_not_ready_stops_before_the_build_with_the_fix(rig, change, words):
    got = rig.run("ios", FAKE_DEVICES=rig.devices(change))
    assert got.returncode == 1 and words in got.stdout and not rig.builds()


def test_the_device_list_is_read_from_the_old_fields_too(rig):
    """devicectl marks hardwareProperties, deviceProperties and connectionProperties deprecated in favour of properties."""
    data = json.loads((FIXTURES / "devices.json").read_text())
    new = apps.parse_devices(data)
    for device in data["result"]["devices"]:
        device.pop("properties")
    assert apps.parse_devices(data) == new and len(new) == 1  # the simulator in the list is not an iPhone to install on
    assert new[0]["paired"] and new[0]["connected"] and new[0]["developer_mode"] == "enabled" and new[0]["os"] == "27.0.1"


@pytest.mark.parametrize("fixture, words", [
    ("xcodebuild_no_account.txt", "Settings (Cmd-,), Accounts"),
    ("xcodebuild_bundle_unavailable.txt", "taken by another team"),
    ("xcodebuild_no_certificate.txt", "Manage Certificates"),
    ("xcodebuild_license.txt", "sudo xcodebuild -license accept"),
    ("xcodebuild_command_line_tools.txt", "sudo xcode-select -s /Applications/Xcode.app"),
])
def test_a_failed_build_names_the_cause_and_the_fix(rig, fixture, words):
    got = rig.run("ios", FAKE_BUILD_ERROR=fixture)
    assert got.returncode == 1 and words in got.stdout and "Full log:" in got.stdout
    assert TEAM not in got.stdout and not [c for c in rig.calls("xcrun") if "install" in c]


@pytest.mark.parametrize("fixture, words", [
    ("devicectl_install_unavailable.txt", "same Wi-Fi"),
    ("devicectl_install_developer_mode.txt", "Developer Mode"),
    ("devicectl_install_expired.txt", "7 days"),
])
def test_a_failed_install_names_the_cause_and_the_fix(rig, fixture, words):
    got = rig.run("ios", FAKE_INSTALL_ERROR=fixture)
    assert got.returncode == 1 and words in got.stdout and "Installing on the iPhone failed" in got.stdout


def test_an_untrusted_developer_is_a_note_not_a_failure(rig):
    got = rig.run("ios", FAKE_LAUNCH_ERROR="devicectl_launch_untrusted.txt")
    assert got.returncode == 0 and "VPN & Device Management" in got.stdout and "Installed." in got.stdout


def test_every_known_error_has_one_diagnosis():
    for path in sorted(FIXTURES.glob("xcodebuild_*.txt")) + sorted(FIXTURES.glob("devicectl_*.txt")):
        if path.name != "xcodebuild_version.txt":
            assert apps.diagnose(path.read_text()), path.name
    assert apps.diagnose("CompileSwift normal arm64 failed: something unrelated") is None


# ---------- the Simulator ----------

def test_sim_builds_unsigned_for_the_newest_iphone_simulator_and_opens_it(rig):
    got = rig.run("ios", "--sim", FAKE_IDENTITIES="find_identity_none.txt")
    assert got.returncode == 0, got.stdout
    build = rig.builds()[0]
    assert build[build.index("-destination") + 1] == "id=27200000-0000-0000-0000-000000000002"  # not the iPad, not iOS 18
    assert not any(a.startswith(("DEVELOPMENT_TEAM", "PRODUCT_BUNDLE_IDENTIFIER")) or a == "-allowProvisioningUpdates" for a in build)
    simctl = [c[2] for c in rig.calls("xcrun") if c[1] == "simctl"]
    assert simctl == ["list", "boot", "bootstatus", "install", "launch"] and not rig.team_file.exists()
    assert "iPhone 18 Pro (iOS 27.2)" in got.stdout


def test_sim_without_an_iphone_simulator_says_where_to_get_one(rig):
    (rig.tmp / "none.json").write_text('{"devices": {}}')
    got = rig.run("ios", "--sim", FAKE_SIMULATORS=str(rig.tmp / "none.json"))
    assert got.returncode == 1 and "Components" in got.stdout and not rig.builds()


# ---------- the Mac app ----------

def test_mac_signs_with_the_team_and_installs_the_app(rig):
    got = rig.run("mac", "--no-open")
    assert got.returncode == 0, got.stdout
    build = rig.builds()[0]
    assert setting(build, "DEVELOPMENT_TEAM") == TEAM and setting(build, "PRODUCT_BUNDLE_IDENTIFIER") == DERIVED + ".mac" and "Release" in build
    assert (rig.apps / "Pointe.app" / "Contents" / "MacOS" / "Pointe").exists()
    assert "Gatekeeper" in got.stdout and "Open Pointe at login" in got.stdout and TEAM not in got.stdout


def test_mac_without_an_apple_account_signs_to_run_locally(rig):
    got = rig.run("mac", "--no-open", FAKE_IDENTITIES="find_identity_none.txt")
    build = rig.builds()[0]
    assert got.returncode == 0 and "CODE_SIGN_IDENTITY=-" in build and setting(build, "DEVELOPMENT_TEAM") == ""
    assert setting(build, "PRODUCT_BUNDLE_IDENTIFIER") is None and "asks for the microphone again" in got.stdout
    assert not rig.team_file.exists()


def test_mac_falls_back_to_a_local_signature_when_the_team_cannot_sign(rig):
    got = rig.run("mac", "--no-open", FAKE_BUILD_ERROR="xcodebuild_no_account.txt")
    assert got.returncode == 0, got.stdout
    assert [setting(b, "DEVELOPMENT_TEAM") for b in rig.builds()] == [TEAM, ""]
    assert "signed to run locally instead" in got.stdout and "Accounts" in got.stdout and (rig.apps / "Pointe.app").is_dir()


def test_mac_replaces_an_older_copy_and_quits_only_the_one_it_replaces(rig):
    old = rig.apps / "Pointe.app" / "Contents" / "MacOS"
    old.mkdir(parents=True)
    (old / "Pointe").write_text("old")
    (old / "Stale").write_text("left over")
    running = rig.tmp / "running"
    running.touch()
    got = rig.run("mac", FAKE_RUNNING=str(running))
    assert got.returncode == 0, got.stdout
    assert (old / "Pointe").read_text() != "old" and not (old / "Stale").exists()
    assert rig.calls("pgrep")[0] == ["pgrep", "-f", re.escape(str(old / "Pointe"))]  # by its full path: another Pointe is left alone
    assert rig.calls("kill") == [["kill", "4242"]] and rig.calls("open")  # it was running, so it is opened again
    assert rig.run("mac", "--no-open").returncode == 0  # and again: the same result


def test_mac_installs_where_dest_says(rig):
    assert rig.run("mac", "--no-open", "--dest", str(rig.tmp / "elsewhere")).returncode == 0
    assert (rig.tmp / "elsewhere" / "Pointe.app").is_dir() and not rig.apps.exists()


# ---------- doctor ----------

def test_doctor_on_a_ready_mac(rig):
    got = rig.run("doctor")
    assert got.returncode == 0, got.stdout
    for words in ("Xcode 27.2", "Apple Development certificate", "Dana's iPhone", "Developer Mode on", DERIVED):
        assert words in got.stdout
    assert got.stdout.count("ready ") == 3 and TEAM not in got.stdout
    assert not rig.team_file.exists() and not rig.bundle_file.exists() and not rig.builds()  # it changes nothing


def test_doctor_without_account_or_iphone_still_has_the_mac_app_and_the_simulator(rig):
    """What the CI runner looks like."""
    got = rig.run("doctor", FAKE_IDENTITIES="find_identity_none.txt", FAKE_DEVICES=rig.devices(None))
    assert got.returncode == 0 and got.stdout.count("ready ") == 2
    assert "not yet" in got.stdout
    assert "a signing certificate, an iPhone" in got.stdout and "Manage Certificates" in got.stdout


@pytest.mark.parametrize("env, words", [
    ({"FAKE_XCODE_VERSION": "xcodebuild_license.txt"}, "sudo xcodebuild -license accept"),
    ({"FAKE_XCODE_VERSION": "xcodebuild_command_line_tools.txt", "FAKE_XCODE_PATH": "/Library/Developer/CommandLineTools"}, "xcode-select -s"),
])
def test_doctor_fails_with_the_fix_when_xcode_cannot_build(rig, env, words):
    got = rig.run("doctor", **env)
    assert got.returncode == 1 and words in got.stdout and "ready " not in got.stdout
    assert rig.run("mac", "--no-open", **env).returncode == 1 and not rig.builds()


def test_doctor_names_what_is_wrong_with_the_iphone(rig):
    off = rig.devices(lambda d: (d["properties"]["state"].update(developerModeStatus={"disabled": {}}), d["deviceProperties"].update(developerModeStatus="disabled")))
    got = rig.run("doctor", FAKE_DEVICES=off)
    assert got.returncode == 0 and "Developer Mode is off" in got.stdout and "the iPhone to be ready" in got.stdout


# ---------- the entry points ----------

def test_pointe_apps_is_the_same_command_and_works_from_any_directory(rig):
    got = subprocess.run([str(ROOT / "bin" / "pointe"), "apps", "mac", "--dry-run"], env=rig.env, cwd="/", capture_output=True, text=True, timeout=60)
    assert got.returncode == 0 and "PointeMac.xcodeproj" in got.stdout
    assert rig.run().returncode == 2 and rig.run("nonsense").returncode == 2


def test_the_script_runs_on_the_python_that_ships_with_xcode():
    """/usr/bin/python3 on a Mac is 3.9: no match statements, no `X | Y` at runtime, standard library only."""
    import ast
    source = (ROOT / "apps.py").read_text()
    tree = ast.parse(source, feature_version=(3, 9))
    assert "from __future__ import annotations" in source
    imported = {(n.module if isinstance(n, ast.ImportFrom) else n.names[0].name).split(".")[0] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))}
    assert imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)
    assert "python3 -I" in (ROOT / "bin" / "pointe-apps").read_text()


def test_the_local_signing_files_are_ignored_by_git():
    ignored = (ROOT / ".gitignore").read_text().split()
    assert {"ios/.team", "ios/.bundle-id", "ios/build/", "macos/build/"} <= set(ignored)


def test_the_docs_name_the_command_and_every_troubleshooting_row_has_its_fix_in_the_tool():
    phone, mac = (ROOT / "docs" / "phone.md").read_text(), (ROOT / "docs" / "mac-app.md").read_text()
    assert "pointe apps ios" in phone and "pointe apps ios --sim" in phone and "pointe apps doctor" in phone and "pointe apps mac" in mac
    for words in ("Manage Certificates", "VPN & Device Management", "Developer Mode", "sudo xcodebuild -license accept", "sudo xcode-select -s", "7 days"):
        assert words in phone, words
    setup = (ROOT / "plugin" / "commands" / "setup.md").read_text()
    assert "bin/pointe apps doctor" in setup and "pointe apps" in (ROOT / "README.md").read_text()


# ---------- the team and bundle ID outlast a plugin update ----------

@pytest.fixture
def plugin_copies(tmp_path, monkeypatch):
    """Claude Code's plugin cache: one folder per version, no .git, the newest being the one that runs."""
    cache = tmp_path / "plugins" / "cache" / "pointe" / "pointe"
    for version in ("1.17.0", "1.18.0", "1.19.0"):
        (cache / version / "ios").mkdir(parents=True)
    monkeypatch.setattr(apps, "ROOT", cache / "1.19.0")
    monkeypatch.setenv("CLAUDE_VOICE_STATE", str(tmp_path / "state"))
    monkeypatch.delenv("POINTE_TEAM_FILE", raising=False)
    monkeypatch.delenv("POINTE_APPS_BUILD", raising=False)
    return cache


def _saved(folder: Path, team: str, bundle: str, age: float) -> None:
    (folder / ".team").write_text(team + "\n")
    (folder / ".bundle-id").write_text(bundle + "\n")
    os.utime(folder / ".team", (time.time() - age, time.time() - age))


def test_a_plugin_update_keeps_the_team_and_bundle_id_so_the_iphone_keeps_one_app(plugin_copies, tmp_path):
    _saved(plugin_copies / "1.17.0" / "ios", "OLDTEAM111", "com.example.old", age=900)
    _saved(plugin_copies / "1.18.0" / "ios", "ABCDE12345", "com.example.mine", age=60)
    assert apps.team_file() == tmp_path / "state" / "apps" / ".team", "the plugin's copy saves outside its version folder"
    assert apps.take_over_saved() == plugin_copies / "1.18.0" / "ios", "the newest earlier copy"
    assert apps.stored_team() == "ABCDE12345"
    args = argparse.Namespace(bundle_id=None, dry_run=False)
    assert apps.resolve_bundle_id(args, "ABCDE12345")[0] == "com.example.mine", "the same app, not a second one"
    assert oct((tmp_path / "state" / "apps" / ".team").stat().st_mode & 0o777) == "0o600"
    assert apps.take_over_saved() is None, "once: afterwards the saved one is the one"
    _saved(plugin_copies / "1.17.0" / "ios", "OLDTEAM111", "com.example.old", age=0)
    assert apps.stored_team() == "ABCDE12345"


def test_builds_of_the_plugin_copy_outlast_it_and_a_clone_keeps_its_own(plugin_copies, tmp_path, monkeypatch):
    assert apps.build_dir("ios") == tmp_path / "state" / "apps" / "build" / "ios"
    clone = tmp_path / "clone"
    (clone / ".git").mkdir(parents=True)
    monkeypatch.setattr(apps, "ROOT", clone)
    assert apps.team_file() == clone / "ios" / ".team" and apps.build_dir("ios") == clone / "ios" / "build" / "apps"
    assert apps.take_over_saved() is None


def test_the_cli_takes_over_an_earlier_copys_team_once_and_says_so(plugin_copies, tmp_path, monkeypatch, capsys):
    _saved(plugin_copies / "1.18.0" / "ios", "ABCDE12345", "com.example.mine", age=60)
    monkeypatch.setattr(apps, "cmd_ios", lambda args: 0)
    assert apps.main(["ios"]) == 0
    assert "an earlier version of Pointe saved" in capsys.readouterr().out
    assert (tmp_path / "state" / "apps" / ".bundle-id").read_text() == "com.example.mine\n"
    apps.main(["ios"])
    assert "earlier version" not in capsys.readouterr().out


def test_a_long_status_word_keeps_a_space_before_its_line(capsys):
    apps.say("not yet", "pointe apps ios       needs a signing certificate")
    apps.say("ok", "built")
    assert capsys.readouterr().out == "not yet pointe apps ios       needs a signing certificate\nok    built\n"


def test_people_build_the_apps_with_the_installed_pointe_and_only_contributors_with_bin_pointe():
    """The plugin puts `pointe` on PATH; `bin/pointe` exists only in a clone. A person reads the README, the site and the
    app docs, so those say `pointe apps`, and `bin/pointe apps` only on a line addressed to contributors."""
    paths = [ROOT / "README.md", ROOT / "docs" / "mac-app.md", ROOT / "docs" / "phone.md", ROOT / "RELEASING.md",
             *sorted((ROOT / "site").glob("**/*.html"))]
    wrong = [f"{p.relative_to(ROOT)}:{n}" for p in paths for n, line in enumerate(p.read_text().splitlines(), 1)
             if re.search(r"(?<![\w/{}$])bin/pointe apps", line) and "ontributors" not in line]
    assert not wrong, "say `pointe apps` (the installed command), or address the line to contributors:\n" + "\n".join(wrong)
