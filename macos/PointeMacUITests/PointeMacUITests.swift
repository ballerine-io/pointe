import XCTest

/// The Mac app against its stub daemon (`-PointeStub`): made-up sessions, no microphone, no network. Each test starts
/// the app fresh. Screenshots go to the runner's own temporary folder (it is sandboxed), in `macos-app-shots`;
/// `macos/test.sh` copies them to /tmp/macos-app-shots.
final class PointeMacUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
    }

    override func tearDown() {
        app?.terminate()
    }

    @MainActor private func launch(_ scenario: String = "busy", _ extra: [String] = []) -> XCUIElement {
        app = XCUIApplication()
        app.launchArguments = ["-PointeStub", scenario, "-PointeOpenWindow", "YES", "-ApplePersistenceIgnoreState", "YES"] + extra
        app.launch()
        app.activate()
        let window = app.windows["pointe.main"]
        XCTAssertTrue(window.waitForExistence(timeout: 10), "the call window opens")
        return window
    }

    @MainActor private func shot(_ name: String, of element: XCUIElement? = nil) {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("macos-app-shots")
        let image = (element ?? app.windows.firstMatch).screenshot()
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            try image.pngRepresentation.write(to: folder.appendingPathComponent("\(name).png"))
        } catch {
            XCTFail("screenshot \(name) was not written: \(error.localizedDescription)")
        }
    }

    @MainActor private func state(_ window: XCUIElement) -> XCUIElement { window.staticTexts["state"] }

    @MainActor private func waitFor(_ element: XCUIElement, label: String, timeout: TimeInterval = 5) {
        let match = NSPredicate(format: "label == %@", label)
        let done = XCTNSPredicateExpectation(predicate: match, object: element)
        XCTAssertEqual(XCTWaiter().wait(for: [done], timeout: timeout), .completed, "\(element.identifier) is “\(element.exists ? element.label : "missing")”, wanted “\(label)”")
    }

    /// The toolbar's Connect: the big one is on the empty stage only, before anything was said.
    @MainActor private func connect(_ window: XCUIElement, to label: String = "Listening") {
        window.toolbars.buttons["callButton"].click()
        waitFor(state(window), label: label)
    }

    @MainActor func testConnectTalkAndHangUp() {
        let window = launch()
        connect(window)
        XCTAssertTrue(window.staticTexts["turn.2"].exists || window.otherElements["turn.2"].exists || window.descendants(matching: .any)["turn.2"].exists)
        shot("02-call")
        window.toolbars.buttons["callButton"].click()
        waitFor(state(window), label: "Not connected")
    }

    @MainActor func testSessionsAreGroupedByMachine() {
        let window = launch()
        XCTAssertTrue(window.staticTexts["studio · this Mac"].waitForExistence(timeout: 5))
        XCTAssertTrue(window.staticTexts["devbox · Linux · 23 ms"].exists)
        let billing = window.descendants(matching: .any)["session.billing"]
        XCTAssertTrue(billing.exists)
        XCTAssertTrue(billing.label.contains("needs you") && billing.label.contains("Codex"), billing.label)
        XCTAssertFalse(billing.label.contains("active"))
        billing.click()
        let active = NSPredicate(format: "label CONTAINS 'active'")
        XCTAssertEqual(XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: active, object: billing)], timeout: 5), .completed)
    }

    @MainActor func testApproveCarriesTheExactRequestAndDenyNeedsNoOne() {
        let window = launch()
        let request = window.staticTexts["request.docs"]
        XCTAssertTrue(request.waitForExistence(timeout: 5))
        XCTAssertEqual(request.value as? String, "Bash(git push origin retry-fix)")
        shot("03-approval")
        window.buttons["approve.docs"].click()
        XCTAssertTrue(request.waitForNonExistence(timeout: 5), "approved: the card is gone")
        app.terminate()

        // Without Touch ID or the password, Approve approves nothing; Deny still works.
        let again = launch("busy", ["-PointeStubOwner", "no"])
        let waiting = again.staticTexts["request.docs"]
        XCTAssertTrue(waiting.waitForExistence(timeout: 5))
        again.buttons["approve.docs"].click()
        Thread.sleep(forTimeInterval: 1.5)
        XCTAssertTrue(waiting.exists, "not approved without the owner")
        again.buttons["deny.docs"].click()
        XCTAssertTrue(waiting.waitForNonExistence(timeout: 5))
    }

    @MainActor func testTypedWordsBecomeATurn() {
        let window = launch()
        connect(window)
        let field = window.textFields["typeField"]
        field.click()
        field.typeText("ship the retry fix")
        window.buttons["sendButton"].click()
        XCTAssertTrue(window.descendants(matching: .any)["turn.6"].waitForExistence(timeout: 5))
        XCTAssertEqual(window.descendants(matching: .any)["turn.6"].label, "Pointe: Noted: ship the retry fix")
    }

    @MainActor func testPushToTalkWithSpaceInTheWindow() {
        let window = launch("busy", ["-PointeStubMic", "ptt"])
        connect(window, to: "Hold to talk")
        window.descendants(matching: .any)["conversation"].click()  // the keyboard is on the conversation, not a field
        XCUIElement.perform(withKeyModifiers: []) { window.typeKey(" ", modifierFlags: []) }
        let held = NSPredicate(format: "value BEGINSWITH 'held '")
        XCTAssertEqual(XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: held, object: state(window))], timeout: 5), .completed,
                       "Space opened and closed the gate: \(String(describing: state(window).value))")
        shot("04-push-to-talk")
    }

    /// The system-wide shortcut (Carbon hot key): pressed while another app is in front, it reaches Pointe, with no
    /// Accessibility or Input Monitoring permission for Pointe. XCUITest's key press has no length; a real hold, with the
    /// press and the release timed, is macos/e2e/hold_shortcut.swift (docs/design/macos-app.md, "Verification").
    @MainActor func testTheGlobalShortcutArrivesFromAnotherApp() {
        let window = launch("busy", ["-PointeStubMic", "ptt"])
        connect(window, to: "Hold to talk")
        let finder = XCUIApplication(bundleIdentifier: "com.apple.finder")
        finder.activate()
        XCTAssertTrue(finder.wait(for: .runningForeground, timeout: 5))
        finder.typeKey(" ", modifierFlags: [.control, .option])
        let arrived = NSPredicate(format: "value == 'open' OR value BEGINSWITH 'held '")
        XCTAssertEqual(XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: arrived, object: state(window))], timeout: 5), .completed,
                       "the shortcut reached Pointe from Finder: \(String(describing: state(window).value))")
        // The release of a press with no length is sometimes lost between XCUITest and the window server (about one run
        // in three here); a held key's release is not (hold_shortcut.swift: 60, 300 and 700 ms holds, each timed right).
        let released = NSPredicate(format: "value BEGINSWITH 'held '")
        let lenient = XCTExpectedFailure.Options()
        lenient.isStrict = false
        XCTExpectFailure("a zero-length synthesized press can lose its release", options: lenient) {
            XCTAssertEqual(XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: released, object: state(window))], timeout: 3), .completed)
        }
    }

    @MainActor func testBrainDumpIsReviewedThenSentOnTheSecondClick() {
        let window = launch()
        connect(window)
        window.toolbars.buttons["dumpButton"].click()
        XCTAssertTrue(window.buttons["dump.done"].waitForExistence(timeout: 5))
        waitFor(state(window), label: "Brain dump")
        shot("05-brain-dump")
        window.buttons["dump.done"].click()
        let send = window.buttons["dump.send"]
        XCTAssertTrue(send.waitForExistence(timeout: 5))
        XCTAssertEqual(send.label, "Send to Orchestrator")
        shot("06-brain-dump-review")
        send.click()
        waitFor(send, label: "Tap again to send")
        send.click()
        XCTAssertTrue(send.waitForNonExistence(timeout: 5), "sent: the review is gone")
    }

    @MainActor func testSettingsHoldThisMacsChoices() {
        let window = launch()
        XCTAssertTrue(window.exists)
        app.menuBars.menuBarItems["Pointe"].click()
        app.menuBars.menuBarItems["Pointe"].menuItems["Settings…"].click()
        let settings = app.windows["com_apple_SwiftUI_Settings_window"]
        XCTAssertTrue(settings.waitForExistence(timeout: 5), "Settings opens")
        app.toolbars.buttons["General"].firstMatch.click()  // Settings reopens on the tab it was left on
        XCTAssertTrue(app.descendants(matching: .any)["settings.theme"].waitForExistence(timeout: 5), "General has the appearance")
        shot("07-settings-general", of: settings)
        app.toolbars.buttons["Voice"].firstMatch.click()
        let shortcut = app.buttons["settings.shortcut"]
        XCTAssertTrue(shortcut.waitForExistence(timeout: 5))
        XCTAssertEqual(shortcut.label, "Talk shortcut: Control Option Space")
        shot("08-settings-voice", of: settings)
        app.toolbars.buttons["Pointe on this Mac"].firstMatch.click()
        let keys = app.descendants(matching: .any)["settings.key.gemini"]
        XCTAssertTrue(keys.waitForExistence(timeout: 5))
        shot("09-settings-daemon", of: settings)
    }

    @MainActor func testTheMenuBarItemSaysWhoNeedsYou() {
        _ = launch()
        let item = app.statusItems.firstMatch
        XCTAssertTrue(item.waitForExistence(timeout: 5))
        let wanted = NSPredicate(format: "title == %@", "Pointe: 2 sessions need you")
        XCTAssertEqual(XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: wanted, object: item)], timeout: 5), .completed, item.title)
        item.click()
        XCTAssertTrue(app.menuItems["Open Pointe"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.menuItems["Connect"].exists)
        app.typeKey(.escape, modifierFlags: [])
    }

    @MainActor func testAnEmptyMacSaysHowToJoinASession() {
        let window = launch("empty")
        XCTAssertTrue(window.staticTexts["No sessions yet"].waitForExistence(timeout: 5))
        XCTAssertEqual(window.staticTexts["connectWhy"].value as? String, "Starts the call on this Mac's microphone")
        shot("01-connect")
        window.buttons["connectButton"].click()
        waitFor(state(window), label: "Listening")
        shot("11-empty-live")
    }
}
