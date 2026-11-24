import XCTest

/// Pairing by a pasted link, and what Connect says when the Mac does not answer. No Mac: the pasted pairing points at a
/// closed port on this machine, so every request fails as an unreachable Mac would.
@MainActor
final class PairPasteUITests: XCTestCase {
    private let fingerprint = String(repeating: "ab", count: 32)
    private let key = String(repeating: "k", count: 40)

    override func setUp() { continueAfterFailure = false }

    private func unpaired() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["POINTE_FORGET"] = "1"
        app.launch()
        XCTAssertTrue(app.buttons["tryDemo"].waitForExistence(timeout: 15), "the pairing screen")
        return app
    }

    private func paste(_ link: String, in app: XCUIApplication) {
        let field = app.textFields["or paste the pointe:// link"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.tap()
        field.typeText(link)
        app.buttons["Pair"].tap()
        let confirm = app.alerts.buttons["confirmPairing"].firstMatch  // a Pointe link asks the owner first
        if confirm.waitForExistence(timeout: 3) { confirm.tap() }
    }

    /// At the accessibility sizes the screen scrolls from the top: the title stays under the clock, the demo link is
    /// whole, and the security note is reached by a swipe. Centred, the stack drew the title over the clock.
    func testAtTheLargestTypeThePairingScreenScrollsAndCutsNothing() {
        let app = XCUIApplication()
        app.launchEnvironment["POINTE_FORGET"] = "1"
        app.launchArguments = ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXL"]
        app.launch()
        let title = app.staticTexts["Pointe"].firstMatch
        XCTAssertTrue(app.buttons["tryDemo"].waitForExistence(timeout: 15), "the pairing screen")
        let header = app.descendants(matching: .any).matching(NSPredicate(format: "label BEGINSWITH %@", "Pointe")).firstMatch
        XCTAssertGreaterThanOrEqual((title.exists ? title : header).frame.minY, 44, "the title is under the status bar")
        let note = app.staticTexts["pairSecurityNote"]
        for _ in 0..<4 where !note.isHittable { app.swipeUp() }
        XCTAssertTrue(note.isHittable, "the security note can be reached")
        XCTAssertLessThanOrEqual(note.frame.maxY, app.windows.firstMatch.frame.maxY + 0.5)
        let demo = app.buttons["tryDemo"]
        XCTAssertTrue(demo.isHittable)
        XCTAssertGreaterThan(demo.frame.height, 60, "the demo link wraps to its whole words instead of ending in an ellipsis")
    }

    func testALinkThatIsNotPointesIsRefusedAndNothingIsPaired() {
        let app = unpaired()
        XCTAssertFalse(app.buttons["Pair"].isEnabled, "nothing to pair yet")
        paste("https://example.com/pair?v=1", in: app)
        XCTAssertTrue(app.staticTexts["That link is not a Pointe pairing link."].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["tryDemo"].exists, "still on the pairing screen")
    }

    /// With the keyboard up (on an SE it leaves under half the screen) the link's error is over the keys, where it is
    /// read. It was drawn under Pair, behind the keys (the intro over the clock is checked on the screenshot: the scroll
    /// is clipped to the safe area, which the accessibility tree does not show).
    func testWithTheKeyboardUpTheLinksErrorShowsAndNothingRunsUnderTheClock() {
        let app = unpaired()
        paste("https://example.invalid/not-a-link", in: app)
        let problem = app.staticTexts["pairProblem"]
        XCTAssertTrue(problem.waitForExistence(timeout: 5))
        XCTAssertEqual(problem.label, "That link is not a Pointe pairing link.")
        let keys = app.keyboards.firstMatch
        XCTAssertTrue(keys.waitForExistence(timeout: 5), "the keyboard is still up")
        XCTAssertTrue(problem.isHittable)
        XCTAssertLessThanOrEqual(problem.frame.maxY, keys.frame.minY, "the error is above the keyboard")
        let field = app.textFields["or paste the pointe:// link"]
        XCTAssertLessThanOrEqual(field.frame.maxY, keys.frame.minY, "the field is above the keyboard")
        let top = app.windows.firstMatch.frame.minY + 20  // the status bar on an SE; a notch is taller and the inset with it
        for element in [problem, field] { XCTAssertGreaterThanOrEqual(element.frame.minY, top) }
    }

    func testAPastedLinkPairsAndConnectSaysTheMacCannotBeReachedAndUnpairNeedsTheOwner() {
        let app = unpaired()
        paste("pointe://pair?v=1&host=127.0.0.1&port=1&fp=\(fingerprint)&key=\(key)", in: app)

        let note = app.descendants(matching: .any)["pairing-note"].firstMatch
        XCTAssertTrue(note.waitForExistence(timeout: 10), "the app says how the pairing went")
        XCTAssertEqual(note.label, "Paired with your Mac.")

        let title = app.staticTexts["problemTitle"]
        XCTAssertTrue(NSPredicate(format: "label == %@", "Pointe is not answering").wait(for: title, timeout: 20),
                      "the status poll finds nothing listening, and the stage says why")
        XCTAssertEqual(app.staticTexts["problemDetail"].label, "127.0.0.1 answered, but nothing listens on port 1.", "with where it looked")
        XCTAssertEqual(app.staticTexts["problemTried"].label, "Tried 127.0.0.1:1 · Wi-Fi")
        let again = app.buttons["problemTryAgain"]
        XCTAssertEqual(again.label, "Try again")
        XCTAssertTrue(app.buttons["problemPairAgain"].exists && app.buttons["problemHowToFix"].exists)
        XCTAssertFalse(app.buttons["typeButton"].isEnabled, "typing needs the call: no field to type into that cannot send")
        XCTAssertEqual(app.staticTexts.matching(NSPredicate(format: "label == %@", "Pointe is not answering")).count, 1,
                       "said once, on the stage (M8)")

        again.tap()  // a call to a Mac that is not there fails and says so again
        sleep(5)  // the attempt ends: a menu opened while the stage changes closes with it
        XCTAssertTrue(again.waitForExistence(timeout: 30), "back to the problem and its Try again")
        XCTAssertFalse(app.buttons["hangUp"].exists, "no call came up")

        let unpair = app.settingsItem("Unpair this phone", .button)
        XCTAssertTrue(unpair.waitForExistence(timeout: 5))
        unpair.tap()
        let sure = app.buttons["Unpair"]
        XCTAssertTrue(sure.waitForExistence(timeout: 5), "Unpair asks first")
        sure.tap()
        // Then Face ID or the passcode, as for a replace: the Simulator has no passcode, so the pairing stays.
        XCTAssertFalse(app.buttons["tryDemo"].waitForExistence(timeout: 5), "no owner check, no unpair")
    }

    func testACodeLinkToAMacThatDoesNotAnswerSaysSoAndPairsNothing() {
        let app = unpaired()
        paste("pointe://pair?v=2&host=127.0.0.1&port=1&fp=\(fingerprint)&code=AB12-CD34", in: app)
        let title = app.staticTexts["problemTitle"]
        XCTAssertTrue(NSPredicate(format: "label == %@", "Pointe is not answering").wait(for: title, timeout: 30),
                      "the trade fails with its cause: \(title.exists ? title.label : "no problem shown")")
        XCTAssertEqual(app.staticTexts["problemDetail"].label, "127.0.0.1 answered, but nothing listens on port 1.")
        XCTAssertTrue(app.buttons["tryDemo"].exists, "still on the pairing screen")
    }
}

extension NSPredicate {
    /// Waits until the element matches; true when it did.
    @MainActor func wait(for element: XCUIElement, timeout: TimeInterval) -> Bool {
        XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: self, object: element)], timeout: timeout) == .completed
    }
}
