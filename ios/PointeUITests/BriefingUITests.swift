import XCTest

/// Audio briefings, on the -demo fixtures: no Mac needed. The ready banner, the Briefing sheet (start, playing controls,
/// skip, stop, the history), never during a meeting, and the schedule settings. Screenshots go to BRIEFING_SHOTS when
/// it names a folder.
@MainActor
final class BriefingUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen]
        app.launch()
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["BRIEFING_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    private func text(_ fragment: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] %@", fragment)).firstMatch
    }

    private func openFromMenu(_ item: String, title: String) {
        let settings = app.buttons["Settings"]
        XCTAssertTrue(settings.waitForExistence(timeout: 15))
        settings.tap()
        let entry = app.buttons[item].firstMatch
        XCTAssertTrue(entry.waitForExistence(timeout: 5), "\(item) is in the settings menu")
        entry.tap()
        XCTAssertTrue(app.navigationBars[title].waitForExistence(timeout: 5), "the \(title) sheet opens")
    }

    func testTheReadyBannerPlaysTheWaitingBriefing() throws {
        launch("briefing")
        XCTAssertTrue(text("Your 08:30 briefing is ready.").waitForExistence(timeout: 15))
        shot("briefing-ready")
        app.buttons["Hear it"].tap()
        XCTAssertTrue(text("Part 1 of 3").waitForExistence(timeout: 5), "it plays, and says how far it is")
        XCTAssertFalse(app.buttons["Hear it"].exists, "the banner is gone once it plays")
    }

    func testTheReadyBannerCanBeDismissed() throws {
        launch("briefing")
        XCTAssertTrue(app.buttons["Dismiss"].waitForExistence(timeout: 15))
        app.buttons["Dismiss"].tap()
        XCTAssertFalse(text("Your 08:30 briefing is ready.").waitForExistence(timeout: 2))
    }

    func testTheSheetStartsSkipsAndStops() throws {
        launch("briefing")
        openFromMenu("Briefing", title: "Briefing")
        XCTAssertTrue(text("It reads; it never sends or approves.").exists, "the lede")
        XCTAssertTrue(app.buttons["The night"].exists && app.buttons["Today"].exists && app.buttons["Yesterday"].exists)
        let start = app.buttons["Brief me"]
        XCTAssertTrue(start.isEnabled, "the demo call is live")
        start.tap()
        XCTAssertTrue(text("Part 1 of 3").waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["Skip"].exists && app.buttons["Stop"].exists)
        shot("briefing-playing")
        app.buttons["Skip"].tap()
        XCTAssertTrue(text("Part 2 of 3").waitForExistence(timeout: 5), "skip goes to the next session")
        app.buttons["Stop"].tap()
        XCTAssertTrue(app.buttons["Brief me"].waitForExistence(timeout: 5), "stopped: it can start again")
        XCTAssertFalse(app.buttons["Skip"].exists)
    }

    func testThePausedBriefingGoesOn() throws {
        launch("briefingPaused")
        openFromMenu("Briefing", title: "Briefing")
        XCTAssertTrue(text("Paused: part 1 of 3").waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["Stop"].exists)
        app.buttons["Go on"].tap()
        XCTAssertTrue(text("Part 2 of 3").waitForExistence(timeout: 5))
    }

    func testTheHistoryShowsEachSessionWithItsState() throws {
        launch("briefing")
        openFromMenu("Briefing", title: "Briefing")
        XCTAssertTrue(text("Last 7 briefings").waitForExistence(timeout: 5))
        XCTAssertTrue(text("· overnight · scheduled").exists, "when, since what, and that it was scheduled")
        XCTAssertTrue(text("Three sessions overnight.").exists, "the opener")
        for chip in ["Needs you", "Failed", "Done"] {
            XCTAssertTrue(text(chip).exists, chip)
        }
        XCTAssertTrue(text("river-lantern waits for your answer on the retry budget.").exists)
        shot("briefing-history")
    }

    func testNotDuringAMeeting() throws {
        launch("meeting")
        openFromMenu("Briefing", title: "Briefing")
        XCTAssertTrue(text("Not during a meeting.").waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["Brief me"].isEnabled)
    }

    func testTheScheduleIsSet() throws {
        launch("briefing")
        openFromMenu("Briefing settings", title: "Briefings")
        let on = app.switches["Scheduled briefing"]
        XCTAssertTrue(on.waitForExistence(timeout: 5))
        XCTAssertEqual(on.value as? String, "1", "the demo has 08:30 on weekdays")
        XCTAssertTrue(text("The briefing is read on your Mac at that time, with or without a call.").exists)
        XCTAssertTrue(app.buttons["day-Mon"].exists && app.buttons["day-Sun"].exists)
        XCTAssertTrue(app.switches["Speak when I connect"].exists && app.switches["Skip empty briefings"].exists)
        app.buttons["day-Sat"].tap()
        XCTAssertTrue(text("Saved.").waitForExistence(timeout: 5))
        on.switches.firstMatch.tap()
        XCTAssertTrue(text("Saved.").waitForExistence(timeout: 5))
        XCTAssertEqual(on.value as? String, "0")
        XCTAssertFalse(app.buttons["day-Mon"].exists, "off: no time and no days")
        shot("briefing-schedule")
    }
}
