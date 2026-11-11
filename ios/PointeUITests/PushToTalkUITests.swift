import XCTest

/// Push to talk on the demo call (no Mac). A press blocks the test until it lifts, so "Talking" during a hold is shown
/// from the `-demo talking` fixture (the Mac's gate open); the hold itself is checked to open and close cleanly.
@MainActor
final class PushToTalkUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String) -> (XCUIApplication, XCUIElement) {
        let app = XCUIApplication()
        app.launchArguments = ["-demo", screen]
        app.launch()
        let line = app.descendants(matching: .any)["statusLine"].firstMatch
        XCTAssertTrue(line.waitForExistence(timeout: 15))
        return (app, line)
    }

    func testSwitchToPushToTalkAndHoldTheRing() {
        let (app, line) = launch("call")
        XCTAssertTrue(line.label.contains("Listening"), line.label)

        app.buttons["Settings"].tap()
        let microphone = app.buttons["microphoneSetting"].firstMatch
        XCTAssertTrue(microphone.waitForExistence(timeout: 5), "Settings has Microphone")
        microphone.tap()
        let ptt = app.buttons["Push to talk"].firstMatch
        XCTAssertTrue(ptt.waitForExistence(timeout: 5))
        ptt.tap()

        XCTAssertTrue(waitFor(line, "Hold to talk"), line.label)
        let ring = app.buttons["Hold to talk"].firstMatch
        XCTAssertTrue(ring.waitForExistence(timeout: 5), "the ring offers to hold")
        ring.press(forDuration: 1.5)
        XCTAssertTrue(waitFor(line, "Hold to talk"), "let go, closed again: \(line.label)")
        app.descendants(matching: .any)["conversation"].firstMatch.press(forDuration: 1.0)  // the caption area holds too
        XCTAssertTrue(waitFor(line, "Hold to talk"), "let go of the conversation: \(line.label)")
        XCTAssertEqual(app.state, .runningForeground)
    }

    func testTheRingAndTheLineShowTheMacsOpenGate() {
        let (app, line) = launch("talking")
        XCTAssertTrue(waitFor(line, "Talking"), line.label)
        XCTAssertTrue(app.buttons["Talking"].firstMatch.waitForExistence(timeout: 5), "the ring says Talking")
    }

    private func waitFor(_ element: XCUIElement, _ text: String, timeout: TimeInterval = 5) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if element.label.contains(text) { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return false
    }
}
