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
    }

    func testALinkThatIsNotPointesIsRefusedAndNothingIsPaired() {
        let app = unpaired()
        XCTAssertFalse(app.buttons["Pair"].isEnabled, "nothing to pair yet")
        paste("https://example.com/pair?v=1", in: app)
        XCTAssertTrue(app.staticTexts["That link is not a Pointe pairing link."].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["tryDemo"].exists, "still on the pairing screen")
    }

    func testAPastedLinkPairsAndConnectSaysTheMacCannotBeReachedThenUnpairGoesBack() {
        let app = unpaired()
        paste("pointe://pair?v=1&host=127.0.0.1&port=1&fp=\(fingerprint)&key=\(key)", in: app)

        let note = app.descendants(matching: .any)["pairing-note"].firstMatch
        XCTAssertTrue(note.waitForExistence(timeout: 10), "the app says how the pairing went")
        XCTAssertEqual(note.label, "Paired with your Mac. Tap Connect to call.")

        // The stage's own identifiers are covered by the conversation's: it is read by its words.
        let title = app.staticTexts["Mac not reachable"]
        XCTAssertTrue(title.waitForExistence(timeout: 20), "the status poll finds no Mac, and the stage says so")
        let why = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "Can't reach your Mac at 127.0.0.1")).firstMatch
        XCTAssertTrue(why.exists, "with where it looked")
        let again = app.buttons["Try again"]
        XCTAssertTrue(again.exists, "one button, Try again")
        XCTAssertEqual(app.staticTexts.matching(NSPredicate(format: "label == %@", "Mac not reachable")).count, 1,
                       "said once, on the stage (M8)")

        again.tap()  // a call to a Mac that is not there fails and says so again
        sleep(5)  // the attempt ends: a menu opened while the stage changes closes with it
        XCTAssertTrue(again.waitForExistence(timeout: 30), "back to Try again")
        XCTAssertFalse(app.buttons["hangUp"].exists, "no call came up")

        app.buttons["Settings"].tap()
        let unpair = app.buttons["Unpair this phone"]
        if !unpair.waitForExistence(timeout: 3) { app.swipeUp() }  // the last item of a long menu
        XCTAssertTrue(unpair.waitForExistence(timeout: 5))
        unpair.tap()
        XCTAssertTrue(app.buttons["tryDemo"].waitForExistence(timeout: 10), "unpaired: back to the pairing screen")
    }

    func testACodeLinkToAMacThatDoesNotAnswerSaysSoAndPairsNothing() {
        let app = unpaired()
        paste("pointe://pair?v=2&host=127.0.0.1&port=1&fp=\(fingerprint)&code=AB12-CD34", in: app)
        let note = app.descendants(matching: .any)["pairing-note"].firstMatch
        XCTAssertTrue(NSPredicate(format: "label BEGINSWITH %@", "Can't reach your Mac at 127.0.0.1.").wait(for: note, timeout: 30),
                      "the trade fails as unreachable: \(note.exists ? note.label : "no note")")
        XCTAssertTrue(app.buttons["tryDemo"].exists, "still on the pairing screen")
    }
}

extension NSPredicate {
    /// Waits until the element matches; true when it did.
    @MainActor func wait(for element: XCUIElement, timeout: TimeInterval) -> Bool {
        XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: self, object: element)], timeout: timeout) == .completed
    }
}
