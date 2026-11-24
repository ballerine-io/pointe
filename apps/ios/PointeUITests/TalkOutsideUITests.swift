import XCTest

/// "Talk to Pointe" from outside the app, driven by apps/ios/e2e/talk_outside_ui.py: a stand-in Mac (talk_mac.py) in
/// Session mode, two sessions that need you, push to talk. The press a Control or the Action button makes is the
/// launch argument `-talkPress` (a Debug build's hook into the same PhoneTalk.press()): the simulator has no Action
/// button. Then the call shows in the Live Activity on the Lock Screen, whose Send and Hang up this test taps. The driver
/// checks what reached the Mac: Orchestrator mode, the press open, closed by Send, the call hung up, and no approval.
@MainActor
final class TalkOutsideUITests: XCTestCase {
    private let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")

    func testAPressStartsACallToTheOrchestratorAndTheLockScreenSendsIt() throws {
        guard let link = ProcessInfo.processInfo.environment["POINTE_PAIR"] else {
            throw XCTSkip("needs the stand-in Mac: run apps/ios/e2e/talk_outside_ui.py")
        }
        let app = XCUIApplication()
        app.launchEnvironment["POINTE_PAIR"] = link
        app.launchArguments += ["-talkPress"]
        app.launch()
        XCTAssertTrue(app.buttons["hangUp"].waitForExistence(timeout: 30), "the press dialled the Mac")
        XCTAssertTrue(app.staticTexts["Talking · tap to send"].waitForExistence(timeout: 10), "and opened a press, saying how to send")
        shot("1-app-talking", XCUIScreen.main.screenshot())

        XCUIDevice.shared.press(.home)
        Thread.sleep(forTimeInterval: 2)
        shot("2-home-island", XCUIScreen.main.screenshot())

        lock()
        Thread.sleep(forTimeInterval: 2)
        // iOS asks, the first times an activity reaches the Lock Screen: "Allow", then "Always Allow"
        let allow = springboard.buttons.matching(NSPredicate(format: "label IN %@", ["Allow", "Always Allow"])).firstMatch
        if allow.waitForExistence(timeout: 3) { allow.tap() }
        shot("3-lock-talking", XCUIScreen.main.screenshot())
        let send = springboard.buttons["Send"]
        XCTAssertTrue(send.waitForExistence(timeout: 10), "the Live Activity offers Send:\n\(springboard.debugDescription)")
        Thread.sleep(forTimeInterval: 1)
        send.tap()
        let hangUp = springboard.buttons["Hang up"]
        XCTAssertTrue(hangUp.waitForExistence(timeout: 10), "after Send: Talk and Hang up")
        XCTAssertTrue(springboard.buttons["Talk"].exists)
        shot("4-lock-sent", XCUIScreen.main.screenshot())
        Thread.sleep(forTimeInterval: 1)  // a tap while the activity redraws its content can be lost
        hangUp.tap()
        if !hangUp.waitForNonExistence(timeout: 6) { hangUp.tap() }
        XCTAssertTrue(hangUp.waitForNonExistence(timeout: 10), "Hang up ended the call and its activity")
        shot("5-lock-ended", XCUIScreen.main.screenshot())
    }

    /// The real path: the Talk to Pointe control in Control Center, with the app not running. It opens Pointe talking to
    /// the orchestrator; the mic sends; then, the app left, the Lock Screen's Hang up ends the call. Needs the control added
    /// once (TalkWidgetUITests.testTheControlInControlCenter).
    func testTheControlInControlCenterOpensPointeTalking() throws {
        guard ProcessInfo.processInfo.environment["POINTE_PAIR"] != nil else {
            throw XCTSkip("needs the stand-in Mac: run apps/ios/e2e/talk_outside_ui.py control")
        }
        let app = XCUIApplication()
        app.terminate()
        XCUIDevice.shared.press(.home)
        let top = springboard.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.005))
        top.press(forDuration: 0.1, thenDragTo: springboard.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.6)))
        let control = springboard.buttons.matching(NSPredicate(format: "label CONTAINS 'Talk to Pointe'")).firstMatch
        guard control.waitForExistence(timeout: 5) else { throw XCTSkip("add the control to Control Center first") }
        mark("tap")
        control.tap()
        let talking = app.staticTexts["Talking · tap to send"]
        XCTAssertTrue(talking.waitForExistence(timeout: 15), "Pointe opened, talking")
        mark("talking")
        shot("6-control-opens-talking", XCUIScreen.main.screenshot())
        Thread.sleep(forTimeInterval: 1)
        let ring = app.buttons["micRing"].firstMatch
        ring.press(forDuration: 0.3)  // a tap on the mic sends
        XCTAssertTrue(talking.waitForNonExistence(timeout: 5), "the tap on the mic sent the press")
        XCTAssertTrue(((ring.value as? String) ?? "").hasPrefix("held"), "the press closed: \(ring.value ?? "")")
        XCUIDevice.shared.press(.home)
        lock()
        Thread.sleep(forTimeInterval: 2)
        let allow = springboard.buttons.matching(NSPredicate(format: "label IN %@", ["Allow", "Always Allow"])).firstMatch
        if allow.waitForExistence(timeout: 3) { allow.tap() }
        let hangUp = springboard.buttons["Hang up"]
        XCTAssertTrue(hangUp.waitForExistence(timeout: 10), "the call on the Lock Screen:\n\(springboard.debugDescription)")
        shot("7-control-lock-on-call", XCUIScreen.main.screenshot())
        Thread.sleep(forTimeInterval: 1)
        hangUp.tap()
        if !hangUp.waitForNonExistence(timeout: 6) { hangUp.tap() }
        XCTAssertTrue(hangUp.waitForNonExistence(timeout: 10), "Hang up ended the call")
    }

    /// The Home Screen widget: added through the Home Screen's editor, then tapped with the app not running. It opens
    /// Pointe talking; the mic sends; Hang up in the app ends the call.
    func testTheHomeScreenWidgetOpensPointeTalking() throws {
        guard ProcessInfo.processInfo.environment["POINTE_PAIR"] != nil else {
            throw XCTSkip("needs the stand-in Mac: run apps/ios/e2e/talk_outside_ui.py widget")
        }
        let app = XCUIApplication()
        app.terminate()
        XCUIDevice.shared.press(.home)
        springboard.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.62)).press(forDuration: 1.5)
        let edit = springboard.buttons["Edit"]
        if edit.waitForExistence(timeout: 5) { edit.tap() }
        springboard.buttons.matching(NSPredicate(format: "label CONTAINS[c] 'Widget'")).firstMatch.tap()
        let search = springboard.searchFields.firstMatch
        XCTAssertTrue(search.waitForExistence(timeout: 5))
        search.tap()
        search.typeText("Pointe")
        springboard.cells.matching(NSPredicate(format: "label CONTAINS 'Pointe'")).firstMatch.tap()
        springboard.buttons.matching(NSPredicate(format: "label ENDSWITH %@", "Add Widget")).firstMatch.tap()
        let done = springboard.buttons["Done"]
        if done.waitForExistence(timeout: 3) { done.tap() }
        Thread.sleep(forTimeInterval: 2)
        shot("8-home-widget", XCUIScreen.main.screenshot())
        let widget = springboard.descendants(matching: .any).matching(NSPredicate(format: "label BEGINSWITH 'Talk to Pointe'")).firstMatch
        XCTAssertTrue(widget.waitForExistence(timeout: 5), springboard.debugDescription)
        mark("tap")
        widget.tap()
        let talking = app.staticTexts["Talking · tap to send"]
        XCTAssertTrue(talking.waitForExistence(timeout: 15), "Pointe opened, talking")
        Thread.sleep(forTimeInterval: 1)
        app.buttons["micRing"].firstMatch.press(forDuration: 0.3)
        XCTAssertTrue(talking.waitForNonExistence(timeout: 5), "the mic sent the press")
        app.buttons["hangUp"].firstMatch.tap()
        XCTAssertTrue(app.buttons["hangUpOff"].waitForExistence(timeout: 10), "hung up")
    }

    /// The side button. XCUIDevice has no public name for it; the simulator honours the private one.
    private func lock() {
        let device = XCUIDevice.shared
        let selector = NSSelectorFromString("pressLockButton")
        if device.responds(to: selector) { device.perform(selector) }
    }

    /// When something happened, for the driver's timings against the stand-in Mac's clock (the same machine's).
    private func mark(_ name: String) {
        guard let dir = ProcessInfo.processInfo.environment["POINTE_SHOTS"], !dir.isEmpty else { return }
        try? String(format: "%.3f", Date().timeIntervalSince1970).write(to: URL(fileURLWithPath: dir).appendingPathComponent("\(name).time"),
                                                                    atomically: true, encoding: .utf8)
    }

    private func shot(_ name: String, _ screenshot: XCUIScreenshot) {
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
        if let dir = ProcessInfo.processInfo.environment["POINTE_SHOTS"] {
            try? screenshot.pngRepresentation.write(to: URL(fileURLWithPath: dir).appendingPathComponent("\(name).png"))
        }
    }
}
