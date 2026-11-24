import XCTest

/// The New pill on a conversation that keeps growing (the longTalk demo adds a line every 1.5 s): it shows once you
/// scroll up to read, and goes when you tap it or scroll back to the newest line yourself.
@MainActor
final class ScrollFollowUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-demo", "longTalk"]
        app.launch()
        XCTAssertTrue(app.scrollViews["conversation"].waitForExistence(timeout: 15))
        return app
    }

    private func readAbove(_ app: XCUIApplication) -> XCUIElement {
        let scroll = app.scrollViews["conversation"]
        scroll.swipeDown(velocity: .slow)
        scroll.swipeDown(velocity: .slow)
        let pill = app.buttons["newLines"]
        XCTAssertTrue(pill.waitForExistence(timeout: 10), "scrolled up while lines arrive: the New pill shows")
        return pill
    }

    func testTappingTheNewPillGoesToTheNewestLineAndThePillGoes() {
        let app = launch()
        let pill = readAbove(app)
        pill.tap()
        XCTAssertTrue(pill.waitForNonExistence(timeout: 4), "the pill goes once the view is at the newest line")
        sleep(4)  // two more lines: the view follows them, so no pill comes back
        XCTAssertFalse(pill.exists, "back at the end, new lines are followed")
    }

    func testScrollingBackToTheEndByHandClearsThePill() {
        let app = launch()
        let pill = readAbove(app)
        let scroll = app.scrollViews["conversation"]
        for _ in 0..<4 where pill.exists { scroll.swipeUp(velocity: .fast) }
        XCTAssertTrue(pill.waitForNonExistence(timeout: 4), "scrolled to the end by hand: the pill goes")
        sleep(4)
        XCTAssertFalse(pill.exists, "and the view follows the next lines")
    }
}
