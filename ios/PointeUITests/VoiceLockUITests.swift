import XCTest

/// The owner-voice lock, on the -demo fixtures: no Mac needed, so these run in every UI test pass. Screenshots go to
/// TEST_RUNNER_VOICE_LOCK_SHOTS when it names a folder.
@MainActor
final class VoiceLockUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen]
        app.launch()
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["VOICE_LOCK_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    private func any(_ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    private func text(_ fragment: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] %@", fragment)).firstMatch
    }

    private func openSheet() {
        let settings = app.buttons["Settings"]
        XCTAssertTrue(settings.waitForExistence(timeout: 15))
        settings.tap()
        let item = app.buttons["Voice lock"].firstMatch
        XCTAssertTrue(item.waitForExistence(timeout: 5), "Voice lock is in the settings menu")
        item.tap()
        XCTAssertTrue(app.navigationBars["Voice lock"].waitForExistence(timeout: 5), "the sheet opens")
    }

    private func help() -> String { any("voiceLockHelp").label }

    /// The system's "Enter iPhone Passcode" sheet, when this simulator has a passcode: closed, which fails the check.
    private func cancelPasscode() {
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let prompt = springboard.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] %@", "Passcode")).firstMatch
        guard prompt.waitForExistence(timeout: 3) else { return }
        let close = springboard.buttons.matching(NSPredicate(format: "label IN %@", ["Cancel", "Close"])).firstMatch
        if close.exists { close.tap() } else { app.coordinate(withNormalizedOffset: CGVector(dx: 0.094, dy: 0.115)).tap() }
        _ = prompt.waitForNonExistence(timeout: 5)
    }

    func testNotEnrolledShowsTheEnrolmentCardAndOnlyOff() throws {
        launch("voiceLock")
        openSheet()
        XCTAssertTrue(text("Pointe can learn your voice").exists, "the intro")
        XCTAssertTrue(app.buttons["Enrol my voice"].isEnabled, "the demo call is live")
        XCTAssertTrue(app.buttons["voiceLevel-off"].isEnabled)
        for level in ["approvals", "commands", "everything"] {
            XCTAssertFalse(app.buttons["voiceLevel-\(level)"].isEnabled, "\(level) needs a voiceprint")
        }
        XCTAssertEqual(help(), "Any voice works, as before.")
        XCTAssertFalse(any("voiceIgnored").exists, "nothing ignored, no counter")
        shot("voice-lock-new")
    }

    func testEnrolling() throws {
        launch("voiceLockEnrolling")
        openSheet()
        XCTAssertTrue(text("Read this line aloud").exists)
        XCTAssertEqual(any("enrolLine").label, "Pack my box with five dozen jugs.")
        XCTAssertTrue(text("42%").exists)
        XCTAssertTrue(text("Didn't count: too quiet").exists)
        XCTAssertTrue(text("Downloading the voice model (40 MB, once)").exists)
        XCTAssertTrue(app.buttons["Cancel"].exists)
        shot("voice-lock-enrolling")
    }

    func testEnrolledLevelsIgnoredAndUnsure() throws {
        launch("voiceLockEnrolled")
        XCTAssertTrue(any("voiceUnsure").waitForExistence(timeout: 15), "three unsure yeses beside the request card")
        XCTAssertEqual(any("voiceUnsure").label, "Tap to approve, or re-enrol.")

        let ignored = app.buttons["voiceIgnored"]
        XCTAssertEqual(ignored.label, "2 ignored (not your voice)")
        shot("voice-lock-call")
        ignored.tap()
        XCTAssertTrue(app.navigationBars["Ignored"].waitForExistence(timeout: 5))
        XCTAssertTrue(text("2.4 s").exists)
        XCTAssertTrue(text("tell docs to delete the branch").exists, "the words, when the Mac sent them")
        XCTAssertTrue(text("1.8 s").exists)
        shot("voice-lock-ignored")
        app.navigationBars["Ignored"].buttons["Done"].tap()

        openSheet()
        XCTAssertTrue(text("Enrolled on: iPhone · AirPods Pro").exists)
        XCTAssertTrue(app.buttons["deleteVoiceprint-iPhone"].exists)
        XCTAssertTrue(app.buttons["Add this device"].exists)
        XCTAssertTrue(app.buttons["Delete my voiceprint"].exists)
        XCTAssertEqual(help(), "A spoken yes counts only in your voice. A no counts from anyone.")
        shot("voice-lock-enrolled")

        // Raising needs nothing.
        app.buttons["voiceLevel-commands"].tap()
        XCTAssertTrue(NSPredicate(format: "label == %@", "Only your voice reaches Pointe. Other voices are listed as ignored, with their words.")
            .evaluate(with: any("voiceLockHelp")), "raised to Commands: \(help())")

        // Lowering needs the owner. A simulator without a passcode fails the check at once; one with a passcode asks, and
        // the test cancels. Either way nothing changes.
        app.buttons["voiceLevel-off"].tap()
        cancelPasscode()
        sleep(1)
        XCTAssertEqual(help(), "Only your voice reaches Pointe. Other voices are listed as ignored, with their words.")

        // Deleting asks once, then needs the owner too.
        app.buttons["Delete my voiceprint"].tap()
        XCTAssertTrue(text("Delete your voiceprint from this Mac? The lock turns off.").waitForExistence(timeout: 5))
    }
}
