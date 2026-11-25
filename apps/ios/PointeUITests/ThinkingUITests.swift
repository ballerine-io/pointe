import XCTest

/// Thinking and working (docs/features/thinking.md), on the -demo fixtures: no Mac needed. From the end of the owner's
/// turn the state line says "Thinking…" where it said "Listening"; while a session has their request it names it. The
/// mute button stays beside the line and there is nothing to skip. Settings has the waiting sound, on, and the progress
/// updates, off. Screenshots go to THINKING_SHOTS.
@MainActor
final class ThinkingUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String, dark: Bool = false) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen, "-demoEnglish", "-pointe.theme", dark ? "dark" : "light"]
        app.launch()
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["THINKING_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    private func line() -> XCUIElement { app.descendants(matching: .any)["statusLine"] }

    private func check(_ screen: String, says words: String, skip: Bool = false) {
        for dark in [false, true] {
            launch(screen, dark: dark)
            XCTAssertTrue(line().waitForExistence(timeout: 10))
            XCTAssertTrue(line().label.hasPrefix(words), "\(screen): the line says \(line().label)")
            XCTAssertTrue(app.buttons["muteButton"].exists, "the mute button stays beside the line")
            XCTAssertEqual(app.buttons["skipButton"].exists, skip, "skip shows only while Pointe speaks")
            shot("iphone-\(screen == "call" ? "listening" : screen)-\(dark ? "dark" : "light")")
            app.terminate()
        }
    }

    func testFromTheEndOfTheTurnTheLineSaysThinking() { check("thinking", says: "Thinking…") }

    func testWhileASessionHasTheRequestTheLineNamesIt() { check("working", says: "billing/main is working…") }

    func testListeningSpeakingAndWritingAreAsBefore() {
        check("call", says: "Listening")
        check("speaking", says: "Speaking…", skip: true)
        check("writing", says: "Writing…")
    }

    func testSettingsHasTheWaitingSoundOnAndTheProgressUpdatesOff() {
        launch("call")
        let cue = app.settingsItem("waitCueSetting", .switch), posted = app.settingsItem("progressSetting", .switch)
        XCTAssertTrue(cue.exists, "Settings has the waiting sound")
        XCTAssertTrue(posted.exists, "and the progress updates")
        XCTAssertEqual(cue.label, "Waiting sound")
        XCTAssertEqual(posted.label, "Progress updates")
        XCTAssertEqual(cue.value as? String, "1", "on unless turned off")
        XCTAssertEqual(posted.value as? String, "0", "off unless turned on")
        shot("iphone-settings-light")
        app.flipSetting("progressSetting")
        XCTAssertEqual(app.switches["progressSetting"].value as? String, "1", "the switch flips")
        app.flipSetting("waitCueSetting")
        XCTAssertEqual(app.switches["waitCueSetting"].value as? String, "0")
    }
}
