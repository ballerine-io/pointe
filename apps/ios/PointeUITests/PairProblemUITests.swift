import XCTest

/// A Mac the phone can't reach, said so it can be fixed (docs/phone.md): the cause, the address and route it tried, and
/// Try again, Pair again and How to fix, on screen until the person acts. The stand-in Mac is a name under `.invalid`,
/// which never resolves anywhere, as a Twingate name does not while its connector is stopped.
@MainActor
final class PairProblemUITests: XCTestCase {
    private let fingerprint = String(repeating: "ab", count: 32)
    private let key = String(repeating: "k", count: 40)
    private let host = "pointe.example.invalid"

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
        let confirm = app.alerts.buttons["confirmPairing"].firstMatch  // the owner's yes to the host and certificate it names
        if confirm.waitForExistence(timeout: 5) { confirm.tap() }
    }

    private func shot(_ app: XCUIApplication, _ name: String) {
        let s = XCTAttachment(screenshot: app.screenshot())
        s.name = name
        s.lifetime = .keepAlways
        add(s)
    }

    /// The owner's morning: an orange line showed at once, went after 15 seconds, and the screen was stuck.
    func testACodeForAMacThatCantBeFoundStaysWithItsCauseAndTheWayForward() {
        let app = unpaired()
        paste("pointe://pair?v=2&host=\(host)&port=7443&fp=\(fingerprint)&code=AB12-CD34", in: app)

        let title = app.staticTexts["problemTitle"]
        XCTAssertTrue(title.waitForExistence(timeout: 30), "the failure is said")
        XCTAssertEqual(title.label, "Can't find your Mac")
        XCTAssertEqual(app.staticTexts["problemDetail"].label, "This phone can't look up \(host).")
        XCTAssertEqual(app.staticTexts["problemTried"].label,
                       "Tried \(host):7443 · a name you route yourself (Twingate, a VPN or a tunnel)")
        XCTAssertTrue(app.staticTexts["problemFix"].label.contains("run colima start"), app.staticTexts["problemFix"].label)
        for id in ["problemTryAgain", "problemPairAgain", "problemHowToFix"] { XCTAssertTrue(app.buttons[id].isHittable, id) }
        shot(app, "1-cant-find-your-mac")

        sleep(20)  // past the 15 s the old note lasted
        XCTAssertTrue(title.exists, "still there: nothing clears it but the person")

        app.buttons["problemHowToFix"].tap()
        XCTAssertTrue(app.staticTexts["helpFix"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["helpFix"].label.contains("connector on the Mac"))
        XCTAssertTrue(app.buttons["helpGuide"].exists || app.links["helpGuide"].exists, "the guide for this route")
        shot(app, "2-how-to-fix")
        app.buttons["helpClose"].tap()
        XCTAssertTrue(title.waitForExistence(timeout: 5), "closing the help leaves the problem")

        app.buttons["problemTryAgain"].tap()  // the same code again, against the same missing name
        XCTAssertTrue(NSPredicate(format: "label == %@", "Can't find your Mac").wait(for: title, timeout: 30))

        app.buttons["problemPairAgain"].tap()
        XCTAssertTrue(NSPredicate(format: "exists == false").wait(for: title, timeout: 5), "Pair again clears it")
        XCTAssertTrue(app.textFields["or paste the pointe:// link"].exists, "and the way to a new code is there")
        shot(app, "3-pair-again")
    }

    func testAPairedPhoneWhoseMacCantBeFoundSaysWhyOnTheCallScreen() {
        let app = unpaired()
        paste("pointe://pair?v=1&host=\(host)&port=7443&fp=\(fingerprint)&key=\(key)", in: app)
        let title = app.staticTexts["problemTitle"]
        XCTAssertTrue(NSPredicate(format: "label == %@", "Can't find your Mac").wait(for: title, timeout: 30),
                      "the status poll finds no Mac, and the stage says why")
        XCTAssertEqual(app.staticTexts["problemTried"].label,
                       "Tried \(host):7443 · a name you route yourself (Twingate, a VPN or a tunnel)")
        for id in ["problemTryAgain", "problemPairAgain", "problemHowToFix"] { XCTAssertTrue(app.buttons[id].exists, id) }
        shot(app, "4-call-screen")
        sleep(5)
        XCTAssertTrue(title.exists, "it stays while the Mac stays away")
    }
}
