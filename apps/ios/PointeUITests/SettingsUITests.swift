import XCTest

/// The call's Settings and the quiet lines of the header, on the demo call (no Mac): Wait before answering, the Talk
/// button only under push to talk, the version line, Keeping your Mac awake, a hold, and Approve behind Face ID.
@MainActor
final class SettingsUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-demo", screen, "-talkStyle", "hold"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["statusLine"].firstMatch.waitForExistence(timeout: 15))
        return app
    }

    private func openSettings(_ app: XCUIApplication) {
        app.openSettings()
        XCTAssertTrue(app.buttons["patienceSetting"].firstMatch.waitForExistence(timeout: 5), "Settings is open")
    }

    private func closeSettings(_ app: XCUIApplication) { app.closeSettings() }

    /// A choice by its words; the ring can carry the same words ("Hold to talk"), and so can the switch over the mic.
    private func item(_ app: XCUIApplication, _ option: String) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label == %@ AND identifier != %@ AND NOT (identifier BEGINSWITH %@)", option,
                                         "micRing", "micModeSwitch")).firstMatch
    }

    private func pick(_ app: XCUIApplication, _ setting: String, _ option: String) {
        app.settingsItem(setting, .button).tap()
        let choice = item(app, option)
        XCTAssertTrue(choice.waitForExistence(timeout: 5), "\(setting) offers \(option)")
        choice.tap()
        app.closeSettings()
    }

    /// The picker's choices mark the one it holds.
    private func holds(_ app: XCUIApplication, _ setting: String, _ option: String) -> Bool {
        app.settingsItem(setting, .button).tap()
        let choice = item(app, option)
        let chosen = choice.waitForExistence(timeout: 5) && choice.isSelected
        app.navigationBars["Settings"].staticTexts["Settings"].tap()  // a tap outside the choices closes them, choosing nothing
        _ = choice.waitForNonExistence(timeout: 3)
        closeSettings(app)
        return chosen
    }

    func testWaitBeforeAnsweringOffersThreeLevelsAndKeepsTheChoice() {
        let app = launch("call")
        XCTAssertTrue(holds(app, "patienceSetting", "Normal"), "the default")
        pick(app, "patienceSetting", "Patient")
        sleep(1)
        XCTAssertTrue(holds(app, "patienceSetting", "Patient"), "the choice holds")
        XCTAssertFalse(holds(app, "patienceSetting", "Normal"))
    }

    func testTheTalkButtonChoiceShowsOnlyUnderPushToTalk() {
        let app = launch("call")
        openSettings(app)
        XCTAssertFalse(app.buttons["talkStyleSetting"].exists, "always on: no talk button to choose")
        closeSettings(app)
        pick(app, "microphoneSetting", "Push to talk")
        sleep(1)
        XCTAssertTrue(holds(app, "talkStyleSetting", "Hold to talk"), "push to talk: Hold to talk by default")
        pick(app, "talkStyleSetting", "Tap to talk")
        XCTAssertTrue(app.buttons["Tap to talk"].firstMatch.waitForExistence(timeout: 5), "the ring follows the choice")
    }

    func testTheHeaderShowsTheVersion() {
        let app = launch("call")
        let header = app.descendants(matching: .any)["versionLine"].firstMatch  // the header reads as one element
        XCTAssertTrue(header.waitForExistence(timeout: 5))
        // The App Store's app never calls itself a beta (App Review 2.2), whatever its version (AppVersion.line).
        XCTAssertNotNil(header.label.range(of: #"Pointe, .*\b\d+\.\d+\.\d+( \(\d+\))?$"#, options: .regularExpression),
                        "the version ends the header: \(header.label)")
        XCTAssertFalse(header.label.contains("beta"), header.label)
    }

    /// The header is Pointe alone; Settings → About credits Ballerine Engineering, with the page's words.
    func testAboutCreditsBallerineEngineeringAndTheHeaderIsPointeAlone() {
        let app = launch("call")
        let header = app.descendants(matching: .any)["versionLine"].firstMatch
        XCTAssertTrue(header.waitForExistence(timeout: 5))
        XCTAssertTrue(header.label.hasPrefix("Pointe, "), "nothing before the name: \(header.label)")
        XCTAssertFalse(header.label.contains("Ballerine"), header.label)
        app.settingsItem("aboutSetting", .button).tap()
        let body = app.staticTexts["aboutBody"].firstMatch
        XCTAssertTrue(body.waitForExistence(timeout: 5))
        XCTAssertEqual(body.label, "Pointe is open source (MIT). Built and open-sourced by Ballerine Engineering.")
        XCTAssertTrue(app.buttons["Source code on GitHub"].exists || app.links["Source code on GitHub"].exists)
        XCTAssertTrue(app.buttons["ballerine.com"].exists || app.links["ballerine.com"].exists)
        XCTAssertTrue(app.descendants(matching: .any)["aboutVersion"].firstMatch.exists)
    }

    func testKeepingTheMacAwakeIsSaidOnlyWhenTheMacSaysSo() {
        let app = launch("machines")
        let line = app.staticTexts["keepAwake"].firstMatch
        XCTAssertTrue(line.waitForExistence(timeout: 5))
        XCTAssertEqual(line.label, "Keeping your Mac awake")
        app.terminate()
        let plain = launch("call")
        XCTAssertFalse(plain.staticTexts["keepAwake"].exists, "the Mac did not say it is keeping awake")
    }

    /// A short title that keeps to one line, and how to go on in the line under it.
    func testAHoldSaysHowToGoOn() {
        let app = launch("hold")
        let line = app.descendants(matching: .any)["statusLine"].firstMatch
        XCTAssertTrue(line.label.hasPrefix("Holding"), line.label)
        XCTAssertTrue(line.label.contains("Say “go ahead” when you're done"), line.label)
        XCTAssertFalse(line.label.contains("Orchestrating"), "the line under the state says how to go on: \(line.label)")
        app.terminate()
        let plain = launch("call")  // the same line with its usual two lines of text, for the height
        let usual = plain.descendants(matching: .any)["statusLine"].firstMatch.frame.height
        plain.terminate()
        let held = launch("hold").descendants(matching: .any)["statusLine"].firstMatch.frame.height
        XCTAssertEqual(held, usual, accuracy: 1, "the title did not wrap")
    }

    /// Approve runs nothing until the owner passes Face ID: another face approves nothing, a matching one answers.
    func testApproveNeedsTheOwnersFace() {
        Biometry.enrol()
        let app = launch("request")
        let approve = app.buttons["Approve"]
        XCTAssertTrue(approve.waitForExistence(timeout: 5))
        approve.tap()
        Biometry.allowFaceID()
        sleep(1)
        Biometry.match(false)
        sleep(2)
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        if springboard.buttons["Cancel"].firstMatch.exists { springboard.buttons["Cancel"].firstMatch.tap() }
        sleep(1)
        XCTAssertTrue(approve.exists && app.buttons["Deny"].exists, "another face approves nothing")

        approve.tap()
        sleep(1)
        Biometry.match(true)
        XCTAssertTrue(approve.waitForNonExistence(timeout: 10), "the owner's face answers the request")
        XCTAssertFalse(app.buttons["Deny"].exists)
    }
}
