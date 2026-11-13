import XCTest

/// What the page did and the app now does too, on the -demo fixtures. No Mac needed.
/// Screenshots go to PARITY_SHOTS when it names a folder.
@MainActor
final class ParityUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen]
        app.launch()
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["PARITY_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    private func any(_ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    func testSettingsShowTheMacsLocalModeReadOnly() throws {
        launch("call")
        XCTAssertTrue(app.buttons["Settings"].waitForExistence(timeout: 15))
        app.buttons["Settings"].tap()
        let line = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label CONTAINS %@", "Voice stays on your Mac · models here")).firstMatch
        if !line.waitForExistence(timeout: 3) { app.swipeUp() }  // a long menu scrolls
        shot("settings-local")
        XCTAssertTrue(line.waitForExistence(timeout: 5), "the local mode line is in Settings")
    }

    /// A screenshot for the eye: XCUITest cannot see where a glyph lands. Hebrew and Arabic end at the left edge.
    func testRightToLeftMessagesSnapshot() throws {
        launch("rtl")
        let bot = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "הבדיקות עוברות")).firstMatch
        XCTAssertTrue(bot.waitForExistence(timeout: 15))
        shot("rtl-conversation")
    }

    func testDisconnectingASessionAsksFirst() throws {
        launch("sessions")
        let row = app.cells.containing(.staticText, identifier: "docs").firstMatch  // the sheet's row, not the chip under it
        XCTAssertTrue(row.waitForExistence(timeout: 15))
        row.swipeLeft()
        app.buttons["Disconnect"].firstMatch.tap()
        let ask = app.staticTexts["Disconnect docs from the voice? It keeps running in its terminal."]
        XCTAssertTrue(ask.waitForExistence(timeout: 5), "a swipe asks before it disconnects")
        shot("disconnect-confirm")
        app.coordinate(withNormalizedOffset: CGVector(dx: 0.2, dy: 0.52)).tap()  // outside the popover: cancel
        XCTAssertTrue(ask.waitForNonExistence(timeout: 5))
        XCTAssertTrue(row.exists, "Cancel keeps the session")
    }

    func testTheSessionsSheetShowsRecentRequestsAndTheContextCount() throws {
        launch("sessions")
        XCTAssertTrue(app.staticTexts["Recent requests"].waitForExistence(timeout: 15) || app.otherElements["Recent requests"].exists)
        app.swipeUp()
        let routed = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "→ docs (named)")).firstMatch
        XCTAssertTrue(routed.waitForExistence(timeout: 5), "where the request went")
        XCTAssertTrue(app.descendants(matching: .any)["contextTokens"].waitForExistence(timeout: 5))
        shot("sessions-recent")
    }

    /// The mic is the call's one primary control: in the middle of the screen, in every state (owner's 1.0 feedback).
    /// Screenshots of each state, per device, go to PARITY_SHOTS for the eye.
    func testTheMicSitsInTheMiddleInEveryState() throws {
        let device = (ProcessInfo.processInfo.environment["SIMULATOR_DEVICE_NAME"] ?? "device").replacingOccurrences(of: " ", with: "-")
        var off: [String] = []
        func measure(_ name: String) {
            let mic = app.buttons.matching(NSPredicate(format: "label IN %@", ["Mute", "Unmute", "Connect", "Talking", "Hold to talk"])).firstMatch
            XCTAssertTrue(mic.waitForExistence(timeout: 15), name)
            shot("mic-\(device)-\(name)")
            let width = app.windows.firstMatch.frame.width
            let gap = mic.frame.midX - width / 2
            if abs(gap) > 1 { off.append("\(name): \(Int(gap)) pt from the middle") }
        }
        for screen in ["call", "talking", "meeting", "drive"] {
            launch(screen)
            measure(screen)
        }
        app.buttons["driveButton"].firstMatch.tap()  // drive mode off: the bar the Mac's 1.0 shows most of the time
        sleep(1)
        measure("drive-off")
        XCTAssertTrue(off.isEmpty, off.joined(separator: "; "))
    }

    func testASessionChipCanBeRenamed() throws {
        launch("call")
        let chip = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "river-lantern")).firstMatch
        XCTAssertTrue(chip.waitForExistence(timeout: 15))
        chip.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).press(forDuration: 1.2)  // under the header material: not "hittable", still on screen
        app.buttons["Rename"].firstMatch.tap()
        let field = app.alerts.textFields.firstMatch
        let opened = field.waitForExistence(timeout: 5)
        shot("rename")
        XCTAssertTrue(opened, "the rename box opens")
        XCTAssertEqual(field.value as? String, "river-lantern", "with the current name")
        app.alerts.buttons["Cancel"].tap()
        XCTAssertTrue(field.waitForNonExistence(timeout: 5))
    }
}
