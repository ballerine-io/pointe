import XCTest

/// Skip and Copy, on the -demo fixtures: no Mac needed. While Pointe speaks, the skip button sits beside the mute button
/// by the status line, and a tap ends the line. A long press on a line of the conversation offers Copy. Screenshots go to SKIP_SHOTS.
@MainActor
final class SkipUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen, "-demoEnglish"]
        app.launch()
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["SKIP_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    func testSkipSitsBesideMuteWhilePointeSpeaksAndEndsTheLine() {
        launch("speaking")
        let skip = app.buttons["skipButton"], mute = app.buttons["muteButton"]
        XCTAssertTrue(skip.waitForExistence(timeout: 10), "while Pointe speaks there is a skip button")
        XCTAssertEqual(skip.label, "Skip this message")
        XCTAssertTrue(mute.exists && skip.isHittable && mute.isHittable)
        XCTAssertFalse(skip.frame.intersects(mute.frame), "the two buttons overlap")
        XCTAssertGreaterThan(skip.frame.minX, mute.frame.maxX, "skip comes after mute, so mute never moves")
        XCTAssertEqual(skip.frame.midY, mute.frame.midY, accuracy: 2, "the two sit on one line")
        XCTAssertLessThanOrEqual(skip.frame.maxX, app.frame.maxX, "the button is on the screen")
        shot("iphone-skip")
        skip.tap()
        XCTAssertTrue(skip.waitForNonExistence(timeout: 5), "the line ended: nothing to skip")
        XCTAssertTrue(mute.exists, "the mute button stays")
    }

    func testWithNothingBeingSaidThereIsNoSkipButton() {
        launch("call")
        XCTAssertTrue(app.buttons["muteButton"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["skipButton"].exists)
    }

    func testALongPressOnALineCopiesIt() {
        launch("speaking")
        let line = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "Pointe: Duplicate charges")).firstMatch
        XCTAssertTrue(line.waitForExistence(timeout: 10))
        line.press(forDuration: 1.0)
        let copy = app.buttons["Copy"]
        XCTAssertTrue(copy.waitForExistence(timeout: 5), "a long press on a line offers Copy")
        shot("iphone-copy")
        copy.tap()  // what lands on the clipboard is Bubble.copyText (SkipTests): a test runner may not read the pasteboard
        XCTAssertTrue(copy.waitForNonExistence(timeout: 5), "the menu closes on Copy")
        XCTAssertTrue(line.exists, "the line is still in the conversation")
    }
}
