import XCTest

/// Wrist approvals and alerts (feature 7). The sheet runs on the -demo fixtures in every pass; the end-to-end test runs
/// only under apps/ios/e2e/alerts_ui.py, which holds a real test daemon and hands cues through TEST_RUNNER_ALERTS_SHOTS.
@MainActor
final class AlertsUITests: XCTestCase {
    private var app: XCUIApplication!
    private let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
    private var shots: String { ProcessInfo.processInfo.environment["ALERTS_SHOTS"] ?? "" }

    override func setUp() { continueAfterFailure = false }

    private func shot(_ name: String) {
        guard !shots.isEmpty else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(shots)/\(name).png"))
    }

    private func cue(_ name: String) { FileManager.default.createFile(atPath: "\(shots)/cue-\(name)", contents: Data()) }

    private func waitForCue(_ name: String, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if FileManager.default.fileExists(atPath: "\(shots)/cue-\(name)") { return true }
            Thread.sleep(forTimeInterval: 0.5)
        }
        return false
    }

    private func labelled(_ root: XCUIElement, _ fragment: String) -> XCUIElement {
        root.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] %@", fragment)).firstMatch
    }

    private func openAlerts() {
        let item = app.settingsItem("Alerts", .button)
        XCTAssertTrue(item.waitForExistence(timeout: 5), "Alerts is in Settings")
        item.tap()
        XCTAssertTrue(app.navigationBars["Alerts"].waitForExistence(timeout: 20), "the sheet opens")
    }

    /// iOS asks once per install; "Allow" if it asks.
    private func turnOnPhoneAlerts() {
        let phone = app.switches["alertsPhone"]
        XCTAssertTrue(phone.waitForExistence(timeout: 5))
        if (phone.value as? String) != "1" { flip(phone) }
        let allow = springboard.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Allow'")).firstMatch
        if allow.waitForExistence(timeout: 8) { allow.tap() }
        XCTAssertTrue(waitFor(phone, value: "1"), "on once iOS allows it")
    }

    private func flip(_ toggle: XCUIElement) { toggle.coordinate(withNormalizedOffset: CGVector(dx: 0.93, dy: 0.5)).tap() }

    private func waitFor(_ element: XCUIElement, value: String, timeout: TimeInterval = 5) -> Bool {
        let e = expectation(for: NSPredicate(format: "value == %@ OR value == %d", value, Int(value) ?? -1), evaluatedWith: element)
        return XCTWaiter.wait(for: [e], timeout: timeout) == .completed
    }

    private func openNotificationCenter() {
        springboard.coordinate(withNormalizedOffset: CGVector(dx: 0.2, dy: 0.01))
            .press(forDuration: 0.1, thenDragTo: springboard.coordinate(withNormalizedOffset: CGVector(dx: 0.2, dy: 0.7)))
        Thread.sleep(forTimeInterval: 1.5)
    }

    func testTheAlertsSheet() throws {
        app = XCUIApplication()
        app.launchArguments = ["-demo", "call"]
        app.launch()
        openAlerts()
        XCTAssertTrue(app.switches["alertsWatchApprove"].exists)
        XCTAssertTrue(app.staticTexts["alertsHelp"].label.contains("never the hidden full text"))
        XCTAssertTrue(labelled(app, "not at all after you swipe it away").exists, "says plainly what works when suspended")
        shot("alerts-sheet")
        // Turning it on lowers what an Approve needs: the passcode (Face ID) first. Cancelled, it stays off.
        let watch = app.switches["alertsWatchApprove"]
        flip(watch)
        let prompt = labelled(springboard, "Enter iPhone Passcode")
        if prompt.waitForExistence(timeout: 5) {
            shot("alerts-passcode")
            app.coordinate(withNormalizedOffset: CGVector(dx: 0.094, dy: 0.115)).tap()  // the sheet's close button
        }
        Thread.sleep(forTimeInterval: 1.5)
        XCTAssertTrue(waitFor(watch, value: "0"), "not confirmed by the owner: it stays off")
        turnOnPhoneAlerts()
    }

    /// A real call; the app leaves the screen with a request pending; the notification shows the read-out form; Approve
    /// on it reaches the session's hook. An unreadable request has Deny only and none of its text. Answered elsewhere, it
    /// is withdrawn.
    func testWristApprovalEndToEnd() throws {
        guard !shots.isEmpty, let link = ProcessInfo.processInfo.environment["POINTE_PAIR"] else {
            throw XCTSkip("alerts: set TEST_RUNNER_ALERTS_SHOTS and TEST_RUNNER_POINTE_PAIR")
        }
        app = XCUIApplication()
        app.launchEnvironment["POINTE_PAIR"] = link
        app.launch()
        let connect = app.buttons["Connect"]
        XCTAssertTrue(connect.waitForExistence(timeout: 30), "paired")
        connect.tap()
        XCTAssertTrue(app.buttons["hangUp"].waitForExistence(timeout: 30), "the call is up")
        let mute = app.buttons["Turn mic off"]
        if mute.waitForExistence(timeout: 5) { mute.tap() }  // the simulator hears the Mac's microphone
        openAlerts()
        turnOnPhoneAlerts()
        app.swipeDown(velocity: .fast)
        cue("ready")

        // A readable request: on screen it is the card; leaving the screen posts it.
        XCTAssertTrue(app.buttons["Deny"].waitForExistence(timeout: 90), "the request is on the card")
        XCUIDevice.shared.press(.home)
        Thread.sleep(forTimeInterval: 2)
        shot("after-home")
        let banner = labelled(springboard, "needs approval")
        if !banner.waitForExistence(timeout: 20) {
            shot("no-banner")
            print("ALERTSDEBUG \(springboard.debugDescription.prefix(4000))")
        }
        XCTAssertTrue(banner.exists, "the notification shows")
        shot("alerts-banner")
        XCTAssertTrue(banner.label.contains("run: git push origin dev"), "the read-out form: \(banner.label)")
        XCTAssertFalse(banner.label.contains("release branch"), "never the model's description")
        banner.press(forDuration: 1.2)
        let approve = springboard.buttons["Approve"]
        XCTAssertTrue(approve.waitForExistence(timeout: 10), "Approve is offered for a request Pointe can read out")
        shot("alerts-actions")
        approve.tap()
        cue("approved")

        // An unreadable request: only its tool, and Deny only.
        XCTAssertTrue(waitForCue("unreadable", timeout: 120))
        let second = labelled(springboard, "open Pointe to see the exact request")
        XCTAssertTrue(second.waitForExistence(timeout: 30), "posted from the background while the call is up")
        XCTAssertFalse(second.label.contains("python3"), "none of its text: \(second.label)")
        second.press(forDuration: 1.2)
        XCTAssertTrue(springboard.buttons["Deny"].waitForExistence(timeout: 10))
        XCTAssertFalse(springboard.buttons["Approve"].exists, "no Approve: it needs the app and Face ID")
        shot("alerts-unreadable")
        XCUIDevice.shared.press(.home)  // closes the expanded notification; it stays in the list
        openNotificationCenter()
        shot("alerts-before-answer")
        XCTAssertTrue(labelled(springboard, "open Pointe to see the exact request").waitForExistence(timeout: 5),
                      "still listed before the Mac answers it")
        XCUIDevice.shared.press(.home)
        cue("unreadable-seen")

        // Answered on the Mac: the app, alive in the background, withdraws it.
        XCTAssertTrue(waitForCue("answered", timeout: 120))
        Thread.sleep(forTimeInterval: 4)  // a few polls
        openNotificationCenter()
        shot("alerts-withdrawn")
        XCTAssertFalse(labelled(springboard, "open Pointe to see the exact request").exists, "withdrawn once answered elsewhere")
        cue("withdrawn")
        XCUIDevice.shared.press(.home)

        app.activate()
        let hangUp = app.buttons["hangUp"]
        if hangUp.waitForExistence(timeout: 10) { hangUp.tap() }
    }
}
