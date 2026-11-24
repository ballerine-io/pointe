import XCTest

/// The conflict alarm on the -demo fixtures: no Mac needed. Screenshots go to CONFLICT_SHOTS when it names a folder.
@MainActor
final class ConflictUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen]
        app.launch()
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["CONFLICT_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    private func any(_ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    private func text(_ fragment: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] %@", fragment)).firstMatch
    }

    func testTheCardShowsBothClaimsAndAsksOnlyWhenTapped() {
        launch("conflict")
        XCTAssertTrue(text("Two sessions disagree").waitForExistence(timeout: 15))
        XCTAssertTrue(any("conflictClaimA").label.contains("ran on staging and passed"), any("conflictClaimA").label)
        XCTAssertTrue(any("conflictClaimB").label.contains("the column does not exist"), any("conflictClaimB").label)
        XCTAssertTrue(any("conflictClaimA").label.contains("river-lantern"))
        XCTAssertTrue(text("The column cannot both exist and be missing.").exists)
        let askA = app.buttons["conflictAsk-a"]
        XCTAssertEqual(askA.label, "Ask river-lantern")
        XCTAssertEqual(app.buttons["conflictAsk-b"].label, "Ask billing/main")
        XCTAssertTrue(askA.isEnabled)
        shot("conflict-card")
        askA.tap()
        XCTAssertTrue(waitForLabel(askA, "Asked river-lantern"), askA.label)
        XCTAssertFalse(askA.isEnabled, "asked once")
        XCTAssertTrue(app.buttons["conflictAsk-b"].isEnabled, "the other side can still be asked")
        app.buttons["conflictDismiss"].tap()
        XCTAssertTrue(any("conflictCard").waitForNonExistence(timeout: 5), "Dismiss removes the card")
    }

    func testInAMeetingTheCardShowsButNothingCanBeAsked() {
        launch("conflictMeeting")
        XCTAssertTrue(any("conflictCard").waitForExistence(timeout: 15))
        XCTAssertEqual(any("conflictMeetingNote").label, "In a meeting, nothing goes to a session: ask after it ends.")
        XCTAssertFalse(app.buttons["conflictAsk-a"].isEnabled)
        XCTAssertFalse(app.buttons["conflictAsk-b"].isEnabled)
        XCTAssertTrue(app.buttons["conflictDismiss"].isEnabled)
        shot("conflict-meeting")
    }

    func testSettingsHasTheConflictAlarm() {
        launch("conflict")
        let item = app.settingsItem("Conflict alarm", .button)
        XCTAssertTrue(item.waitForExistence(timeout: 5), "Conflict alarm is in Settings")
        item.tap()
        XCTAssertTrue(app.navigationBars["Conflict alarm"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.switches["conflictsOn"].waitForExistence(timeout: 5))
        XCTAssertTrue(text("Check sessions against each other").exists)
        XCTAssertTrue(text("It never asks a session on its own.").exists)
        shot("conflict-settings")
    }

    func testNoCardWithoutAConflict() {
        launch("call")
        XCTAssertTrue(any("statusLine").waitForExistence(timeout: 15))
        XCTAssertFalse(any("conflictCard").exists)
    }

    private func waitForLabel(_ element: XCUIElement, _ label: String, timeout: TimeInterval = 5) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if element.label == label { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        }
        return element.label == label
    }
}
