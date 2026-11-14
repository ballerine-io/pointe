import XCTest

/// "Try a demo" on the pairing screen: what App Review sees without a Mac. No launch arguments, as in a Release build.
@MainActor
final class DemoUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    func testTryADemoFromThePairingScreenAndLeaveIt() {
        let app = XCUIApplication()
        app.launchEnvironment["POINTE_FORGET"] = "1"
        app.launch()

        let tryDemo = app.buttons["tryDemo"]
        XCTAssertTrue(tryDemo.waitForExistence(timeout: 15), "the pairing screen offers the demo")
        tryDemo.tap()

        let badge = app.buttons["demoBadge"]
        XCTAssertTrue(badge.waitForExistence(timeout: 10), "the demo says it is one")
        XCTAssertEqual(badge.label, "Exit demo")
        let deny = app.buttons["Deny"]
        XCTAssertTrue(deny.waitForExistence(timeout: 5), "a sample request waits for an answer")
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "git push --force-with-lease")).firstMatch.exists,
                      "the exact command is on screen")
        deny.tap()
        XCTAssertTrue(deny.waitForNonExistence(timeout: 5), "the answer clears the card, as a Mac would")

        badge.tap()
        XCTAssertTrue(tryDemo.waitForExistence(timeout: 10), "out of the demo, back to pairing")
        XCTAssertFalse(app.buttons["demoBadge"].exists)
    }

    func testTheLaunchArgumentDemoShowsNoBadge() {
        let app = XCUIApplication()
        app.launchArguments = ["-demo", "request"]
        app.launch()
        XCTAssertTrue(app.buttons["Approve"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.buttons["demoBadge"].exists, "screenshots and tests keep the plain header")
    }
}
