"""The Mac app's main flows, driven through the Accessibility API on the demo fixtures: no daemon, no microphone, no
network, nothing of the room. It is what `apps/macos/test.sh ui` checks with XCUITest, for a Mac where nobody is there to
unlock Automation Mode: the terminal needs only the Accessibility permission. Run by hand, or by `apps/macos/test.sh smoke`:

    python3 -I apps/macos/e2e/smoke.py [--shots /tmp/parity-shots/mac]

It builds the app (apps/macos/build.sh), and for each flow starts the build-folder app fresh with `-demo <screen>` (the
iPhone UI suite's fixtures: invented sessions), presses its controls by their identifiers, and checks what is on
screen. The app's own settings are untouched: a demo keeps nothing. Never the installed app.
"""

import os
import plistlib
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
results: list[tuple[str, bool]] = []
SHOTS = Path(sys.argv[sys.argv.index("--shots") + 1]) if "--shots" in sys.argv else None


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}"[:240], flush=True)


class App:
    """One launch of the built app. `env` points it at a made-up state folder when the flow is about no daemon."""

    def __init__(self, binary: Path, driver: Path, *args: str, look: str = "dark", env: dict | None = None):
        self.driver = driver
        bubble = [] if "-pointe.bubble" in args else ["-pointe.bubble", "NO"]
        self.proc = subprocess.Popen([str(binary), "-PointeOpenWindow", "YES", "-ApplePersistenceIgnoreState", "YES", "-pointe.theme", look,
                                      *bubble, *args],
                                     env={**os.environ, **(env or {})}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.wait("pointe.main", 15)

    def ax(self, *words: str) -> subprocess.CompletedProcess:
        return subprocess.run([str(self.driver), str(self.proc.pid), *words], capture_output=True, text=True)

    def has(self, ident: str) -> bool:
        return self.ax("exists", ident).returncode == 0

    def wait(self, ident: str, timeout: float = 8, gone: bool = False) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self.has(ident) != gone:
                return True
            time.sleep(0.25)
        return False

    def press(self, ident: str) -> bool:
        return self.ax("press", ident).returncode == 0

    def shot(self, name: str, look: str) -> None:
        if SHOTS is None:
            return
        SHOTS.mkdir(parents=True, exist_ok=True)
        window = self.ax("window").stdout.strip()
        if window:
            subprocess.run(["screencapture", "-x", "-o", "-l", window, str(SHOTS / f"{name}-{look}.png")], check=False)

    def quit(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


SHEETS = {  # -sheet <name>: an identifier that is on that sheet
    "settings": "microphoneSetting", "voiceLock": "voiceLockHelp", "alerts": "alertsPhone", "dictionary": "dictionaryLearn",
    "machines": "inviteMachine", "conflictSettings": "conflictsOn", "showSettings": "showSetting", "about": "aboutBody",
}
SCREENS = {  # -demo <screen>: an identifier that screen shows
    "call": "conversation", "request": "requestCommand", "meeting": "notesFeed", "whisper": "whisperCard", "conflict": "conflictCard",
    "startPending": "startConfirm", "hold": "statusLine", "rtl": "conversation", "longRequest": "requestCommand", "many": "sessionsColumn",
    "machinesSessions": "sessionsColumn", "empty": "statusLine", "noSessions": "statusLine",
}


def shared_bundle_ids(app: Path) -> list[str]:
    """The resource bundles inside `app` that carry the app's own identifier. PRODUCT_BUNDLE_IDENTIFIER on the
    xcodebuild command line sets it on every target, PointeUI's resource bundle too, and then the Chorus mark does not
    load from that bundle's asset catalog: the header shows no mark."""
    def ident(info: Path) -> str | None:
        return plistlib.loads(info.read_bytes()).get("CFBundleIdentifier") if info.is_file() else None
    own = ident(app / "Contents" / "Info.plist")
    return sorted(b.name for b in (app / "Contents" / "Resources").glob("*.bundle")
                  if own and own in (ident(b / "Contents" / "Info.plist"), ident(b / "Info.plist")))


def main() -> int:
    # POINTE_SMOKE_APP: an app already built (apps/macos/build.sh's, or another plain build). A demo keeps nothing, so it needs
    # no bundle ID of its own; never pass PRODUCT_BUNDLE_IDENTIFIER to xcodebuild for it (shared_bundle_ids).
    given = os.environ.get("POINTE_SMOKE_APP")
    built = subprocess.CompletedProcess([], 0, given, "") if given else \
        subprocess.run([str(ROOT / "apps" / "macos" / "build.sh")], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    work = Path(tempfile.mkdtemp(prefix="pointe-mac-smoke-"))
    driver = work / "axdrive"
    tool = subprocess.run(["swiftc", "-O", str(ROOT / "apps" / "macos" / "e2e" / "axdrive.swift"), "-o", str(driver)], capture_output=True, text=True)
    check("the app and the driver built", built.returncode == 0 and tool.returncode == 0, (built.stderr or tool.stderr)[-300:])
    if built.returncode or tool.returncode:
        return 1
    bundle = Path(built.stdout.strip().splitlines()[-1])
    assert "/build/" in str(bundle), "the app under test is the one in the build folder, never an installed one"
    binary = bundle / "Contents" / "MacOS" / "Pointe"
    shared = shared_bundle_ids(bundle)
    check("the app's resource bundles keep their own identifiers, so the Chorus mark loads", not shared,
          f"{', '.join(shared)} carry the app's identifier: build without PRODUCT_BUNDLE_IDENTIFIER on the command line"
          if shared else "")
    if shared:
        return 1

    def start(*args: str, look: str = "dark", env: dict | None = None) -> App:
        return App(binary, driver, *args, look=look, env=env)

    # the call screen, wide and narrow
    for look in ("dark", "light"):
        app = start("-demo", "call", look=look)
        try:
            ok = app.wait("statusLine")
            if look == "dark":
                check("the call screen is the shared one: state line, conversation, mic, hang up", ok and all(app.has(i) for i in ("conversation", "micRing", "hangUp", "dumpButton", "typeButton")))
                check("a wide window lists the sessions in its left column, with New session and Settings at its foot",
                      all(app.has(i) for i in ("sessionsColumn", "session.billing/main", "session.docs", "newSession", "sideSettings", "modePicker")))
                check("starting drive mode is the phone's: no Drive button", not app.has("driveButton"))
            app.shot("call", look)
            if look == "dark":
                app.ax("size", "520", "720")
                check("a narrow window has the phone's layout: no column, the Sessions button", app.wait("sessionsColumn", 4, gone=True) and app.has("sessionsButton"))
                app.shot("call-narrow", look)
                app.ax("size", "900", "680")
                check("wide again, the column is back", app.wait("sessionsColumn", 4))
        finally:
            app.quit()

    # a request: Deny in the window
    for look in ("dark", "light"):
        app = start("-demo", "request", look=look)
        try:
            shown = app.wait("requestCommand")
            app.shot("request", look)
            if look == "dark":
                check("a request's card has the exact command, Deny and Approve", shown and app.has("requestDeny") and app.has("requestApprove")
                      and "git push" in app.ax("texts", "requestCommand").stdout)
                app.press("requestDeny")
                check("Deny answers at once (no Touch ID) and the card goes", app.wait("requestCommand", 6, gone=True))
        finally:
            app.quit()

    # typing, the brain dump, the menus
    app = start("-demo", "call")
    try:
        app.wait("statusLine")
        check("Type opens the type bar", app.press("typeButton") and app.wait("typeField"))
        check("Brain dump replaces the conversation with its panel", app.press("dumpButton") and app.wait("dump.panel"))
        app.shot("brain-dump", "dark")
        check("Done structures it and the review opens", app.press("dump.done") and app.wait("dump.send", 10))
        app.shot("brain-dump-review", "dark")
    finally:
        app.quit()
    app = start("-demo", "call")
    try:
        app.wait("statusLine")
        check("the Settings… menu command opens Settings", app.ax("menu", "Settings…").returncode == 0 and app.wait("microphoneSetting"))
        check("with this Mac's own sections after the shared ones", all(app.has(i) for i in ("settings.shortcut", "settings.bubble", "settings.login", "settings.daemon", "settings.folders.add")))
        check("and no Unpair this phone", "Unpair this phone" not in app.ax("labelled", "Unpair").stdout)
    finally:
        app.quit()
    for title, ident in (("New Session", "newSessionStart"), ("Type Instead of Talking", "typeField"), ("About Pointe", "aboutBody"),
                         ("Machines", "inviteMachine"), ("Sessions and Mode", "sessionsColumn")):
        app = start("-demo", "machines" if title == "Machines" else "call")
        try:
            app.wait("statusLine")
            check(f"the menu command {title} does its thing", app.ax("menu", title).returncode == 0 and app.wait(ident), ident)
        finally:
            app.quit()

    # the call bubble: on a call it floats with the state and the talk mode, as the window says it; × hides it
    app = start("-demo", "call", "-pointe.bubble", "YES")
    try:
        app.wait("statusLine")
        mode = app.ax("label", "bubble.mode").stdout.strip()
        check("on a call the bubble shows the state and the talk mode", app.wait("bubble.state") and app.has("bubble.talk") and app.has("bubble.close"), mode)
        check("the window names the same talk mode", mode != "" and mode == app.ax("label", "talkMode").stdout.strip(), mode)
        app.shot("bubble", "dark")
        check("× hides the bubble", app.press("bubble.close") and app.wait("bubble.state", 4, gone=True))
    finally:
        app.quit()
    app = start("-demo", "call", "-pointe.bubble", "YES", "-pointe.bubble.small", "YES")
    try:
        check("small, the bubble is a pill with the state and the talk mode's glyph", app.wait("bubble.small") and not app.has("bubble.state"))
    finally:
        app.quit()

    # reading mode: the card, Unread and Read on Pointe's lines, Mark all read, Talk again; the toggle in Settings
    for look in ("dark", "light"):
        app = start("-demo", "reading", "-demoEnglish", look=look)
        try:
            shown = app.wait("readingCard")
            app.shot("reading", look)
            if look == "dark":
                check("reading mode shows its card and an unread line", shown and app.has("readingUnread") and app.has("readingRead"))
                check("Mark all read reads every line", app.press("readingMarkRead") and app.wait("readingUnread", 4, gone=True))
                check("Talk again ends it: the card goes", app.press("readingOff") and app.wait("readingCard", 4, gone=True))
        finally:
            app.quit()
    app = start("-demo", "reading", "-sheet", "settings")
    try:
        check("Settings has the Read toggle beside Whisper", app.wait("microphoneSetting") and app.has("readingToggle"))
    finally:
        app.quit()

    # session mode: the held news badge, open, with Tell me; another session's request stays on its card
    for look in ("dark", "light"):
        app = start("-demo", "held", "-demoEnglish", look=look)
        try:
            shown = app.wait("heldBadge")
            app.shot("held", look)
            if look == "dark":
                check("session mode shows the held news badge, open, with Tell me", shown and app.has("heldTell")
                      and "2 updates from other sessions" in app.ax("label", "heldBadge").stdout)
                check("another session's request stays on its card, with Approve", app.has("requestCommand") and app.has("requestApprove"))
                check("Tell me asks for the held news (the demo empties the badge)", app.press("heldTell") and app.wait("heldBadge", 4, gone=True))
        finally:
            app.quit()

    # the composer: Shift+Return and Option+Return write a new line, Return sends the lines whole
    app = start("-demo", "call")
    try:
        app.wait("statusLine")
        app.press("typeButton")
        app.wait("typeField")
        app.ax("set", "typeField", "Rename the column")
        app.ax("return", "typeField", "shift")
        time.sleep(0.4)
        first = app.ax("value", "typeField").stdout
        check("Shift+Return writes a new line in the field", first.rstrip(" ").endswith("column\n") or "column\n" in first, repr(first))
        app.ax("set", "typeField", "Rename the column\\nThen migrate")
        app.ax("return", "typeField", "option")
        time.sleep(0.4)
        second = app.ax("value", "typeField").stdout
        check("Option+Return writes a new line too", "migrate\n" in second, repr(second))
        app.ax("set", "typeField", "Rename the column\\nThen migrate")
        app.ax("return", "typeField")
        time.sleep(0.6)
        said = app.ax("texts", "conversation").stdout
        check("Return sends it, its line break kept", "Rename the column\nThen migrate" in said and app.ax("value", "typeField").stdout.strip() == "",
              repr(said[-120:]))
    finally:
        app.quit()

    # every sheet and every demo screen opens
    for sheet, ident in SHEETS.items():
        for look in (("dark", "light") if sheet in ("settings", "voiceLock", "dictionary") else ("dark",)):
            app = start("-demo", {"machines": "machines", "voiceLock": "voiceLock"}.get(sheet, "call"), "-sheet", sheet, look=look)
            try:
                ok = app.wait(ident)
                if look == "dark":
                    check(f"the {sheet} sheet opens", ok, ident)
                app.shot(f"sheet-{sheet}", look)
            finally:
                app.quit()
    for screen, ident in SCREENS.items():
        app = start("-demo", screen)
        try:
            check(f"the {screen} screen draws", app.wait(ident), ident)
            if screen in ("meeting", "whisper", "conflict", "rtl", "many"):
                app.shot(screen, "dark")
        finally:
            app.quit()

    # no Pointe on this Mac: the setup guide, and the demo from it
    empty = work / "state"
    empty.mkdir()
    app = start("-pointe.bubble", "YES", env={"CLAUDE_VOICE_STATE": str(empty), "CLAUDE_VOICE_DAEMON_PORT": "7999", "CLAUDE_CONFIG_DIR": str(work / "claude")})
    try:
        check("with no daemon the window is the setup guide", app.wait("setup", 10) and not app.has("conversation"))
        check("and with no call there is no bubble saying Not connected", not app.has("bubble.state") and not app.has("bubble.small"))
        app.shot("setup", "dark")
        check("on the setup guide the Settings… menu command opens Settings, with the keys",
              app.ax("menu", "Settings…").returncode == 0 and app.wait("settings.key.gemini"))
        app.ax("button", "Done")
        app.wait("settings.key.gemini", 4, gone=True)
        check("and About Pointe opens About", app.ax("menu", "About Pointe").returncode == 0 and app.wait("aboutBody"))
        app.ax("button", "Done")
        app.wait("aboutBody", 4, gone=True)
        check("Try a demo shows the call screen with a request", app.press("tryDemo") and app.wait("requestCommand", 8) and app.has("demoBadge"))
    finally:
        app.quit()

    # the first launch from Pointe.dmg, with nothing installed (-PointeSetupPreview, Debug only: nothing is looked for,
    # installed or started): Install Pointe, its progress bar, then the one question and the key
    for state, ident in (("fresh", "install"), ("installing", "install.progress"), ("setup", "setup.free"), ("key", "setup.key.gemini")):
        app = start("-PointeSetupPreview", state, look="light", env={"CLAUDE_VOICE_STATE": str(empty), "CLAUDE_VOICE_DAEMON_PORT": "7999"})
        try:
            check(f"first launch, {state}: the setup shows {ident}", app.wait(ident, 10) and app.has("setup.progress"))
            app.shot(f"first-launch-{state}", "light")
        finally:
            app.quit()

    failed = [name for name, ok in results if not ok]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed" + (f"; failed: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
