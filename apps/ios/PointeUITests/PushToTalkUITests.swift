import XCTest

/// Push to talk on the demo call (no Mac). A press blocks the test until it lifts, so what a press did is read after it
/// from the ring's debug trace ("held 2415 ms": how long the gate was held), and "Talking" during a hold from the
/// `-demo talking` fixture (the Mac's gate open). Tap to talk leaves the gate open between taps, so it is read directly.
@MainActor
final class PushToTalkUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String) -> (XCUIApplication, XCUIElement) {
        let app = XCUIApplication()
        app.launchArguments = ["-demo", screen, "-talkStyle", "hold"]  // the choice is kept on the device: start from the default
        app.launch()
        let line = app.descendants(matching: .any)["statusLine"].firstMatch
        XCTAssertTrue(line.waitForExistence(timeout: 15))
        return (app, line)
    }

    private func pick(_ app: XCUIApplication, _ setting: String, _ option: String) {
        let picker = app.settingsItem(setting, .button)
        XCTAssertTrue(picker.waitForExistence(timeout: 5), "Settings has \(setting)")
        picker.tap()
        let choice = app.buttons[option].firstMatch
        if !choice.waitForExistence(timeout: 3) { picker.tap() }  // a tap while the sheet still settles opens no menu
        XCTAssertTrue(choice.waitForExistence(timeout: 5))
        choice.tap()
        app.closeSettings()
    }

    /// "held 2415 ms" -> 2415; nil when no press was taken.
    private func heldMs(_ ring: XCUIElement) -> Int? {
        let value = (ring.value as? String) ?? ""
        guard value.hasPrefix("held ") else { return nil }
        return Int(value.split(separator: " ")[1])
    }

    func testSwitchToPushToTalkAndHoldTheRing() {
        let (app, line) = launch("call")
        XCTAssertTrue(line.label.contains("Listening"), line.label)
        pick(app, "microphoneSetting", "Push to talk")
        XCTAssertTrue(waitFor(line, "Hold to talk"), line.label)
        let ring = app.buttons["Hold to talk"].firstMatch
        XCTAssertTrue(ring.waitForExistence(timeout: 5), "the ring offers to hold")
        ring.press(forDuration: 1.5)
        XCTAssertTrue(waitFor(line, "Hold to talk"), "let go, closed again: \(line.label)")
        app.descendants(matching: .any)["conversation"].firstMatch.press(forDuration: 1.0)  // the caption area holds too
        XCTAssertTrue(waitFor(line, "Hold to talk"), "let go of the conversation: \(line.label)")
        XCTAssertEqual(app.state, .runningForeground)
    }

    /// The ring felt dead: a press must open at touch down (not at the lift, not after a round trip), and a tap, which
    /// hears no word, must say where Tap to talk is.
    func testAHoldOpensAtTouchDownAndATapPointsAtTapToTalk() {
        let (app, line) = launch("call")
        pick(app, "microphoneSetting", "Push to talk")
        XCTAssertTrue(waitFor(line, "Hold to talk"), line.label)
        let ring = app.buttons["micRing"].firstMatch
        ring.press(forDuration: 2.5)
        RunLoop.current.run(until: Date().addingTimeInterval(0.3))
        let held = heldMs(ring)
        XCTAssertNotNil(held, "the hold was not taken: \(ring.value ?? "")")
        XCTAssertGreaterThan(held ?? 0, 2000, "opened late: \(held ?? 0) ms of a 2500 ms hold")
        let value = (ring.value as? String) ?? ""
        let gate = value.range(of: #"gate \+(\d+) ms"#, options: .regularExpression).map { Int(value[$0].dropFirst(6).dropLast(3)) ?? 9999 }
        XCTAssertLessThan(gate ?? 9999, 150, "the touch reached the gate late: \(value)")
        XCTAssertTrue(waitFor(line, "Sent") || waitFor(line, "Hold to talk"), line.label)
        ring.tap()
        XCTAssertTrue(waitFor(line, "or choose Tap to talk in Settings", timeout: 2), "a tap said nothing: \(line.label)")
        XCTAssertLessThan(heldMs(ring) ?? 9999, 250)
        XCTAssertTrue(waitFor(line, "Hold to talk", timeout: 4), line.label)
        XCTAssertFalse(line.label.contains("Talking"), "a tap left the gate open: \(line.label)")
    }

    /// The Mac's status is polled: right after a lift it still says open. A press then was swallowed whole.
    func testAHoldWhileTheMacStillShowsOpenIsTaken() {
        let (app, line) = launch("talking")
        XCTAssertTrue(waitFor(line, "Talking"), line.label)
        let ring = app.buttons["micRing"].firstMatch
        ring.press(forDuration: 1.0)
        RunLoop.current.run(until: Date().addingTimeInterval(0.3))
        XCTAssertGreaterThan(heldMs(ring) ?? 0, 700, "the press was swallowed: \(ring.value ?? "")")
    }

    func testTapToTalkOpensOnOneTapAndSendsOnTheNext() {
        let (app, line) = launch("call")
        pick(app, "microphoneSetting", "Push to talk")
        XCTAssertTrue(waitFor(line, "Hold to talk"), line.label)
        pick(app, "talkStyleSetting", "Tap to talk")
        XCTAssertTrue(waitFor(line, "Tap to talk"), line.label)
        let ring = app.buttons["micRing"].firstMatch
        XCTAssertTrue(app.buttons["Tap to talk"].firstMatch.waitForExistence(timeout: 5), "the ring offers a tap")
        ring.tap()
        XCTAssertTrue(waitFor(line, "Talking · tap to send"), "one tap did not open: \(line.label)")
        RunLoop.current.run(until: Date().addingTimeInterval(1.5))
        XCTAssertTrue(line.label.contains("Talking"), "the gate did not stay open between taps: \(line.label)")
        XCTAssertTrue(app.buttons["Talking"].firstMatch.exists, "the ring says Talking")
        ring.tap()
        XCTAssertTrue(waitFor(line, "Sent"), "the second tap did not send: \(line.label)")
        XCTAssertTrue(waitFor(line, "Tap to talk", timeout: 3), line.label)
        XCTAssertGreaterThan(heldMs(ring) ?? 0, 1000, "\(ring.value ?? "")")
        app.descendants(matching: .any)["conversation"].firstMatch.press(forDuration: 1.0)  // a long press on the words toggles too
        XCTAssertTrue(waitFor(line, "Talking · tap to send"), line.label)
        RunLoop.current.run(until: Date().addingTimeInterval(1.5))  // the open gate's line scrolls the view: a touch on a scrolling view stops it
        app.descendants(matching: .any)["conversation"].firstMatch.press(forDuration: 1.0)
        XCTAssertTrue(waitFor(line, "Tap to talk", timeout: 3), line.label)
    }

    /// The owner could not find push to talk: it was only in the ••• menu. The switch over the mic, as on the page, is the
    /// same setting as in Settings, and the ring follows it at once.
    func testTheSwitchOverTheMicSetsTheMicrophone() {
        let (app, line) = launch("call")
        let control = app.segmentedControls["micModeSwitch"]
        XCTAssertTrue(control.waitForExistence(timeout: 5), "the switch is on the call screen")
        XCTAssertTrue(control.isHittable, "and in reach")
        XCTAssertTrue(control.buttons["Always on"].isSelected, "Always on, as the Mac says")
        control.buttons["Hold to talk"].tap()
        XCTAssertTrue(waitFor(line, "Hold to talk"), line.label)
        XCTAssertTrue(app.buttons["micRing"].label == "Hold to talk", "the ring holds to talk now")
        let setting = app.settingsItem("microphoneSetting", .button)
        XCTAssertTrue("\(setting.label) \(setting.value ?? "")".contains("Push to talk"), "Settings agrees: \(setting.label)")
        app.closeSettings()
        control.buttons["Always on"].tap()
        XCTAssertTrue(waitFor(line, "Listening"), line.label)
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
