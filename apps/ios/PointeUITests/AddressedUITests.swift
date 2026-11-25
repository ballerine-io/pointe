import XCTest

/// Addressed speech (docs/features/addressed-speech.md), on the -demo fixtures: no Mac needed. The switch above the
/// mic has "Say “Pointe”" between Always on and Hold to talk; with the mode on the state line says how to talk;
/// Settings → Microphone has "Only when I say Pointe" and says what it does. Screenshots go to ADDRESSED_SHOTS.
@MainActor
final class AddressedUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String, dark: Bool = false) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen, "-demoEnglish", "-pointe.theme", dark ? "dark" : "light"]
        app.launch()
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["ADDRESSED_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    private func line() -> XCUIElement { app.descendants(matching: .any)["statusLine"].firstMatch }

    func testTheSwitchHasTheModeBetweenAlwaysOnAndHoldToTalk() {
        launch("call")
        let mode = app.descendants(matching: .any)["micModeSwitch"].firstMatch
        XCTAssertTrue(mode.waitForExistence(timeout: 15))
        let choices = mode.buttons.allElementsBoundByIndex.map(\.label)
        XCTAssertEqual(choices, ["Always on", "Say “Pointe”", "Hold to talk"], "in this order")
        let window = app.windows.firstMatch.frame
        XCTAssertTrue(window.contains(mode.frame), "three choices fit above the mic: \(mode.frame) in \(window)")
        XCTAssertTrue(line().label.hasPrefix("Listening"), "always on says Listening, as before")
    }

    func testWithTheModeOnTheStateLineSaysHowToTalk() {
        for dark in [false, true] {
            launch("addressed", dark: dark)
            XCTAssertTrue(line().waitForExistence(timeout: 15))
            XCTAssertTrue(line().label.hasPrefix("Say “Pointe” to talk"), line().label)
            let mode = app.descendants(matching: .any)["micModeSwitch"].firstMatch
            XCTAssertTrue(mode.buttons["Say “Pointe”"].isSelected, "the switch shows the mode")
            XCTAssertTrue(app.buttons["micRing"].exists && app.buttons["muteButton"].exists, "the microphone and mute are as in always on")
            shot("iphone-addressed-\(dark ? "dark" : "light")")
            app.terminate()
        }
    }

    func testSettingsHasTheModeAndSaysWhatItDoes() {
        launch("addressed")
        let setting = app.settingsItem("microphoneSetting")
        XCTAssertTrue(setting.exists, "Settings has the microphone")
        XCTAssertTrue(setting.label.contains("Only when I say Pointe") || (setting.value as? String ?? "").contains("Only when I say Pointe"),
                      "it shows the mode: \(setting.label) \(String(describing: setting.value))")
        let hint = app.settingsItem("addressedHint")
        XCTAssertTrue(hint.exists && hint.label.contains("Anything else is dropped"), "and says what it does")
        shot("iphone-addressed-settings-light")
    }
}
