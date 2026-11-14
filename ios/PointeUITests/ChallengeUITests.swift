import XCTest

/// Challenge me, on the -demo fixtures: no Mac needed. The panel with the plan and the exchange, ending it, closing an
/// ended one, starting from the settings menu and from a brain dump's review, and never during a meeting. Screenshots go to
/// CHALLENGE_SHOTS when it names a folder.
@MainActor
final class ChallengeUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen]
        app.launch()
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["CHALLENGE_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    private func text(_ fragment: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] %@", fragment)).firstMatch
    }

    private var panel: XCUIElement { app.descendants(matching: .any)["challenge.panel"] }

    private func openMenu() -> XCUIElement {
        let settings = app.buttons["Settings"]
        XCTAssertTrue(settings.waitForExistence(timeout: 15))
        settings.tap()
        let entry = app.buttons["menu.challenge"]
        XCTAssertTrue(entry.waitForExistence(timeout: 5), "Challenge is in the settings menu")
        return entry
    }

    /// A tap on a menu item while the menu is still opening is dropped, and the menu stays up: tap until it closes.
    private func pick(_ item: XCUIElement) {
        for _ in 0..<3 {
            item.tap()
            if item.waitForNonExistence(timeout: 3) { return }
        }
    }

    func testThePanelShowsThePlanAndTheExchange() throws {
        launch("challenge")
        XCTAssertTrue(panel.waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts["Challenging"].exists, "the state line")
        XCTAssertEqual(app.staticTexts["challenge.title"].label, "Challenge")
        XCTAssertTrue(text("I argue against your plan, one objection at a time. Nothing is sent while it's on.").exists)
        XCTAssertTrue(text("The plan").exists)
        XCTAssertTrue(text("Move the checkout retries into a queue").exists)
        XCTAssertTrue(text("Objection: A queue replays the charge on failover").exists)
        let answer = app.descendants(matching: .any)["challenge.item.rebuttal"]
        XCTAssertTrue(answer.exists, "the user's answer")
        XCTAssertTrue(answer.label.hasPrefix("You: ") && answer.label.contains("אידמפוטנטי"), "in Hebrew: \(answer.label)")
        XCTAssertTrue(text("Objection: The gateway ignores that key").exists)
        XCTAssertTrue(text("Or say “you've made your point”, “verdict” or “back to normal”.").exists)
        XCTAssertFalse(app.buttons["challenge.close"].exists, "no Close while it is on")
        XCTAssertTrue(app.buttons["Mute"].isHittable, "the mic stays reachable")
        shot("challenge-on")
    }

    func testEndChallengeEndsItAndCloseHidesIt() throws {
        launch("challenge")
        let end = app.buttons["challenge.end"]
        XCTAssertTrue(end.waitForExistence(timeout: 15))
        XCTAssertEqual(end.label, "End challenge")
        end.tap()
        XCTAssertTrue(app.buttons["challenge.close"].waitForExistence(timeout: 5), "ended: it can be closed")
        XCTAssertEqual(app.staticTexts["challenge.title"].label, "Challenge ended")
        XCTAssertFalse(app.buttons["challenge.end"].exists)
        XCTAssertFalse(app.staticTexts["Challenging"].exists)
        app.buttons["challenge.close"].tap()
        XCTAssertFalse(panel.waitForExistence(timeout: 2), "closed here")
        XCTAssertTrue(app.scrollViews["conversation"].exists, "back to the conversation")
    }

    func testAnEndedChallengeShowsItsVerdictUntilClosed() throws {
        launch("challengeEnded")
        XCTAssertTrue(panel.waitForExistence(timeout: 15))
        XCTAssertEqual(app.staticTexts["challenge.title"].label, "Challenge ended")
        XCTAssertTrue(text("Verdict: Ship the retry fix behind a flag").exists)
        XCTAssertFalse(text("Or say “you've made your point”").exists, "no hint once ended")
        shot("challenge-ended")
        app.buttons["challenge.close"].tap()
        XCTAssertFalse(panel.waitForExistence(timeout: 2))
        let entry = openMenu()
        XCTAssertEqual(entry.label, "Challenge")
        pick(entry)
        XCTAssertTrue(panel.waitForExistence(timeout: 5), "a new challenge shows again")
        XCTAssertEqual(app.staticTexts["challenge.title"].label, "Challenge")
    }

    func testTheMenuStartsAChallengeWithNoPlanYet() throws {
        launch("call")
        let entry = openMenu()
        XCTAssertEqual(entry.label, "Challenge")
        XCTAssertTrue(entry.isEnabled, "the demo call is live")
        pick(entry)
        XCTAssertTrue(panel.waitForExistence(timeout: 5))
        XCTAssertTrue(text("No plan yet: say it in a sentence or two.").exists)
        XCTAssertTrue(app.staticTexts["Challenging"].exists)
        let again = openMenu()
        XCTAssertEqual(again.label, "End challenge", "while on, the menu ends it")
    }

    func testABrainDumpInReviewCanBeChallenged() throws {
        launch("brainDumpReview")
        let button = app.buttons["dump.challenge"]
        XCTAssertTrue(button.waitForExistence(timeout: 15))
        XCTAssertEqual(button.label, "Challenge it")
        XCTAssertTrue(app.buttons["dump.send"].exists, "in the review, next to Send")
        shot("challenge-brain-dump")
        button.tap()
        XCTAssertTrue(panel.waitForExistence(timeout: 5))
        XCTAssertTrue(text("stop the checkout timing out").exists, "the structured prompt is the plan")
    }

    func testNotDuringAMeeting() throws {
        launch("meeting")
        XCTAssertFalse(openMenu().isEnabled)
    }
}
