import XCTest

/// Settings (the ••• button) while the status changes under it: the longTalk demo adds a line every 1.5 s, as a live
/// call's polls do. The Menu it replaced could not be scrolled to its end here: each change built it again, back at its
/// top. The sheet stays where you scrolled it, and stays open.
@MainActor
final class MenuStabilityUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func openSettings() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-demo", "longTalk"]
        app.launch()
        XCTAssertTrue(app.scrollViews["conversation"].waitForExistence(timeout: 15))
        app.buttons["Settings"].tap()
        XCTAssertTrue(app.navigationBars["Settings"].waitForExistence(timeout: 5), "Settings is open")
        return app
    }

    func testSettingsKeepsItsScrollWhileTheStatusChanges() {
        let app = openSettings()
        let last = app.buttons["Unpair this phone"]
        for _ in 0..<4 where !(last.exists && last.isHittable) { app.collectionViews.firstMatch.swipeUp(velocity: .slow) }
        XCTAssertTrue(last.exists && last.isHittable, "scrolled to the end of Settings")
        let at = last.frame
        sleep(5)  // three new lines
        XCTAssertTrue(last.exists && last.isHittable, "still open, still at its end")
        XCTAssertEqual(last.frame.minY, at.minY, accuracy: 2, "it did not jump back to its top")
    }

    /// Every item the menu had is in Settings: the call's screens, the microphone, and the settings with sheets of their own.
    func testEveryItemOfTheOldMenuIsReachable() {
        let app = openSettings()
        let list = app.collectionViews.firstMatch
        let items = ["microphoneSetting", "patienceSetting", "Clean up my words", "whisperItem", "dictionaryItem",
                     "Sessions and mode", "machinesItem", "Start a meeting", "Briefing", "menu.challenge",
                     "Briefing settings", "Meeting settings", "Alerts", "Voice lock", "Conflict alarm", "showSettingItem",
                     "driveSuggestSetting", "appearanceSetting", "localMode", "aboutSetting", "Unpair this phone"]
        var missing: [String] = []
        for item in items {
            let element = app.descendants(matching: .any)[item].firstMatch
            for _ in 0..<6 where !element.exists { list.swipeUp(velocity: .slow) }
            if !element.exists { missing.append(item) }
        }
        XCTAssertEqual(missing, [], "every item of the old menu is in Settings")
    }

    /// A row with a sheet of its own: Settings closes, that sheet opens.
    func testARowOpensItsOwnSheet() {
        let app = openSettings()
        app.settingsItem("Alerts", .button).tap()
        XCTAssertTrue(app.navigationBars["Settings"].waitForNonExistence(timeout: 5), "Settings closed")
        XCTAssertTrue(app.navigationBars["Alerts"].waitForExistence(timeout: 5), "the Alerts sheet opened")
    }
}
