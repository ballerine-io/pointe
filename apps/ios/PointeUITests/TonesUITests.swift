import XCTest

/// Session tones (docs/features/session-tones.md), on the -demo fixtures: no Mac needed. Settings has the switch, off
/// unless turned on, and it flips. Screenshots go to TONES_SHOTS.
@MainActor
final class TonesUITests: XCTestCase {
    func testSettingsHasSessionTonesOffAndTheSwitchFlips() {
        continueAfterFailure = false
        for dark in [false, true] {
            let app = XCUIApplication()
            app.launchArguments = ["-demo", "call", "-demoEnglish", "-pointe.theme", dark ? "dark" : "light"]
            app.launch()
            let tones = app.settingsItem("sessionTonesSetting", .switch)
            XCTAssertTrue(tones.exists, "Settings has session tones")
            XCTAssertEqual(tones.label, "Session tones")
            XCTAssertEqual(tones.value as? String, "0", "off unless turned on")
            let footer = app.descendants(matching: .any)["waitFooter"].firstMatch
            XCTAssertTrue(footer.waitForExistence(timeout: 5) && footer.label.contains("A short tone before a background session's report"),
                          "the footer says what the switch does: \(footer.label)")
            if let folder = ProcessInfo.processInfo.environment["TONES_SHOTS"] {
                try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/iphone-tones-settings-\(dark ? "dark" : "light").png"))
            }
            app.flipSetting("sessionTonesSetting")
            XCTAssertEqual(app.switches["sessionTonesSetting"].value as? String, "1", "the switch flips")
            app.terminate()
        }
    }
}
