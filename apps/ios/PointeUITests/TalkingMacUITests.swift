import XCTest

/// Driven by apps/ios/e2e/talking_mac_ui.py, which runs a stand-in Mac that streams bot audio and pings, and passes the
/// pairing link in TEST_RUNNER_POINTE_PAIR. The driver judges the pongs; this only holds the call up while it listens.
final class TalkingMacUITests: XCTestCase {
    func testTheCallStaysUpWhileTheMacTalks() throws {
        guard let link = ProcessInfo.processInfo.environment["POINTE_PAIR"],
              let secs = Double(ProcessInfo.processInfo.environment["POINTE_HOLD_SECS"] ?? "") else {
            throw XCTSkip("needs the stand-in Mac: run apps/ios/e2e/talking_mac_ui.py")
        }
        let app = XCUIApplication()
        app.launchEnvironment["POINTE_PAIR"] = link
        app.launch()
        let connect = app.buttons["Connect"]
        XCTAssertTrue(connect.waitForExistence(timeout: 20), "the app paired and shows Connect")
        connect.tap()
        XCTAssertTrue(app.buttons["hangUp"].waitForExistence(timeout: 20), "the call is up")
        if ProcessInfo.processInfo.environment["POINTE_BACKGROUND"] == "1" {  // the phone in a pocket: another app in front
            XCUIDevice.shared.press(.home)
            Thread.sleep(forTimeInterval: secs)
            app.activate()
        } else {
            Thread.sleep(forTimeInterval: secs)
        }
        XCTAssertTrue(app.buttons["hangUp"].exists, "the call is still up")
    }
}
