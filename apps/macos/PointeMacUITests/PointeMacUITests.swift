import XCTest

/// The Mac app on the demo fixtures the iPhone app's UI tests use (`-demo <screen>`): invented sessions, no daemon, no
/// microphone, no network. The window is the shared call screen, so the identifiers are the iPhone suite's; these
/// tests are the Mac's side of the same flows: the sessions column, a request's card, Settings with this Mac's own
/// sections, typing, the brain dump, and the menu bar's commands and their keys. Each test starts the app fresh.
/// Screenshots go to the runner's own temporary folder (it is sandboxed), in `macos-app-shots`; `apps/macos/test.sh` copies
/// them to /tmp/macos-app-shots.
///
/// macOS lets XCUITest drive an app only after a person unlocks Automation Mode (`automationmodetool`), so these do not
/// run unattended; `apps/macos/e2e/smoke.py` drives the same flows through the Accessibility API and does.
final class PointeMacUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
    }

    override func tearDown() {
        app?.terminate()
    }

    @MainActor private func launch(_ screen: String = "request", _ extra: [String] = []) -> XCUIElement {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen, "-PointeOpenWindow", "YES", "-ApplePersistenceIgnoreState", "YES"] + extra
        app.launch()
        app.activate()
        let window = app.windows["pointe.main"]
        XCTAssertTrue(window.waitForExistence(timeout: 10), "the call window opens")
        return window
    }

    @MainActor private func shot(_ name: String) {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("macos-app-shots")
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            try app.windows.firstMatch.screenshot().pngRepresentation.write(to: folder.appendingPathComponent("\(name).png"))
        } catch {
            XCTFail("screenshot \(name) was not written: \(error.localizedDescription)")
        }
    }

    @MainActor private func any(_ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    @MainActor func testTheCallScreenIsTheSharedOneWithTheSessionsColumn() {
        let window = launch("call")
        XCTAssertTrue(any("statusLine").waitForExistence(timeout: 5))
        XCTAssertTrue(any("sessionsColumn").exists, "a wide window lists the sessions in its left column, as the page does")
        XCTAssertTrue(any("session.billing/main").exists && any("session.docs").exists)
        XCTAssertTrue(any("conversation").exists && any("micRing").exists && any("hangUp").exists)
        XCTAssertFalse(any("driveButton").exists, "drive mode starts on the phone")
        _ = window
        shot("01-call")
    }

    @MainActor func testARequestsCardHasTheCommandDenyAndApprove() {
        _ = launch("request")
        XCTAssertTrue(any("requestCommand").waitForExistence(timeout: 5))
        // The buttons themselves: the first element carrying an identifier can be its container (here the card's scroll
        // view, which has no hit point: "Unable to find hit point for ScrollView" every CI run), as Connect's toolbar was.
        let deny = app.buttons.matching(identifier: "requestDeny").firstMatch
        XCTAssertTrue(deny.exists && app.buttons.matching(identifier: "requestApprove").firstMatch.exists)
        shot("02-request")
        func denied() {  // Deny needs no one; the demo's card goes, as a Mac's would
            deny.click()
            XCTAssertTrue(any("requestCommand").waitForNonExistence(timeout: 5), "the card goes")
        }
        guard ProcessInfo.processInfo.environment["CI"] == "true" else { return denied() }
        // Still an expected failure in CI until a run shows this step pass with the button queried (CONTRIBUTING.md, UI
        // tests in CI); not strict, so a pass is not a failure.
        let options = XCTExpectedFailure.Options()
        options.isStrict = false
        XCTExpectFailure("macOS 26 runner: Deny had no hit point while the card's scroll view answered for it", options: options,
                         failingBlock: denied)
    }

    @MainActor func testSettingsHaveTheSharedRowsAndThisMacsOwn() {
        _ = launch("call")
        any("settingsButton").click()
        XCTAssertTrue(any("microphoneSetting").waitForExistence(timeout: 5))
        for id in ["patienceSetting", "appearanceSetting", "aboutSetting", "settings.shortcut", "settings.bubble", "settings.login", "settings.daemon",
                   "settings.folders.add"] {
            XCTAssertTrue(any(id).exists, id)
        }
        XCTAssertFalse(app.buttons["Unpair this phone"].exists, "nothing to unpair on the Mac")
        shot("03-settings")
        app.typeKey(.escape, modifierFlags: [])
        XCTAssertFalse(any("microphoneSetting").waitForExistence(timeout: 2), "Esc closes a sheet")
    }

    @MainActor func testTheMenusKeysOpenTheirSheets() {
        _ = launch("call")
        app.typeKey(",", modifierFlags: .command)
        XCTAssertTrue(any("microphoneSetting").waitForExistence(timeout: 5), "⌘, is Settings")
        app.typeKey(.escape, modifierFlags: [])
        app.typeKey("n", modifierFlags: .command)
        XCTAssertTrue(any("newSessionStart").waitForExistence(timeout: 5), "⌘N is New Session")
        app.typeKey(.escape, modifierFlags: [])
        app.typeKey("t", modifierFlags: .command)
        XCTAssertTrue(any("typeField").waitForExistence(timeout: 5), "⌘T is the type bar")
    }

    @MainActor func testTheNightShiftHasItsStripItsLedgerAndItsKey() {
        _ = launch("nightShift")
        XCTAssertTrue(any("nightShiftStrip").waitForExistence(timeout: 5), "a running shift shows its strip")
        XCTAssertTrue(any("nightShiftStop").exists)
        shot("06-night-shift")
        app.typeKey("n", modifierFlags: [.command, .shift])
        XCTAssertTrue(any("nightShiftHeadline").waitForExistence(timeout: 5), "⇧⌘N is the night shift's ledger")
        XCTAssertTrue(any("nightShiftSection.decided").exists && any("nightShiftLedgerStop").exists)
        shot("07-night-shift-ledger")
        any("nightShiftLedgerStop").click()
        XCTAssertTrue(any("nightShiftOpenStart").waitForExistence(timeout: 5), "stopped: another can start")
        any("nightShiftOpenStart").click()
        XCTAssertTrue(any("nightShiftTask.0").waitForExistence(timeout: 5))
        XCTAssertTrue(any("nightShiftNotify").exists && any("nightShiftStart").exists)
        shot("08-night-shift-start")
    }

    @MainActor func testTypingAndTheBrainDump() {
        _ = launch("call")
        any("typeButton").click()
        XCTAssertTrue(any("typeField").waitForExistence(timeout: 5))
        any("dumpButton").click()
        XCTAssertTrue(any("dump.panel").waitForExistence(timeout: 5), "the brain dump replaces the conversation")
        shot("04-brain-dump")
    }

    @MainActor func testANarrowWindowHasThePhonesStripInsteadOfTheColumn() {
        let window = launch("call")
        XCTAssertTrue(any("sessionsColumn").waitForExistence(timeout: 5))
        let corner = window.coordinate(withNormalizedOffset: CGVector(dx: 1, dy: 1)).withOffset(CGVector(dx: -3, dy: -3))
        corner.press(forDuration: 0.2, thenDragTo: window.coordinate(withNormalizedOffset: CGVector(dx: 0.45, dy: 1)))
        XCTAssertFalse(any("sessionsColumn").waitForExistence(timeout: 2), "narrow: the strip of sessions and the Sessions sheet")
        XCTAssertTrue(any("sessionsButton").exists)
        shot("05-narrow")
    }
}
