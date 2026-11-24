import XCTest

/// Words in the meeting sheets, on the -demo fixtures (docs/design/ux-review-ios.md, "left as it is").
@MainActor
final class SheetWordsUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func launch(_ arguments: [String]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = arguments
        app.launch()
        return app
    }

    /// A bare number beside a name said nothing: it is the speaker's count of turns.
    func testTheSpeakersSheetSaysWhatItCounts() {
        let app = launch(["-demo", "meeting", "-sheet", "speakers"])
        XCTAssertTrue(app.navigationBars["Speakers"].waitForExistence(timeout: 15))
        for count in ["9 turns", "14 turns", "6 turns"] {
            XCTAssertTrue(app.staticTexts[count].exists, count)
        }
        XCTAssertFalse(app.staticTexts["9"].exists, "no bare count")
    }

    func testStartingAMeetingSaysWhatPointeDoesThere() {
        let app = launch(["-demo", "meetingStart"])
        XCTAssertTrue(app.navigationBars["Start a meeting"].waitForExistence(timeout: 15))
        let lede = "Pointe sits in and takes notes for you. It stays quiet unless you let it speak."
        XCTAssertTrue(app.staticTexts[lede].waitForExistence(timeout: 5), "under the two modes")
    }
}
