import XCTest

/// Driven by tests/e2e/ios_app.py, which runs a test daemon and passes the pairing link in TEST_RUNNER_POINTE_PAIR.
final class PointeUITests: XCTestCase {
    func testPairConnectAndDenyARequest() throws {
        let link = try XCTUnwrap(ProcessInfo.processInfo.environment["POINTE_PAIR"], "set TEST_RUNNER_POINTE_PAIR")
        let app = XCUIApplication()
        app.launchEnvironment["POINTE_PAIR"] = link
        app.launch()

        let connect = app.buttons["Connect"]
        XCTAssertTrue(connect.waitForExistence(timeout: 20), "the app paired and shows Connect")
        connect.tap()
        XCTAssertTrue(app.buttons["Hang up"].waitForExistence(timeout: 20), "the call is up")

        // The simulator hears the Mac's microphone: room talk must not answer the request before the tap does.
        let mute = app.buttons["Mute"]
        if mute.waitForExistence(timeout: 5) { mute.tap() }
        let deny = app.buttons["Deny"]
        XCTAssertTrue(deny.waitForExistence(timeout: 90), "the pending request shows, with Deny")
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "touch phone-check.txt")).firstMatch.exists,
                      "the exact command is on screen")
        deny.tap()
        XCTAssertTrue(deny.waitForNonExistence(timeout: 15), "the request is answered")
        app.buttons["Hang up"].tap()
        XCTAssertTrue(connect.waitForExistence(timeout: 15))
    }
}
