import XCTest

/// Show while it says, on the -demo fixtures: the card, the sheet and its tabs, and the setting. No Mac needed.
/// Screenshots go to TEST_RUNNER_SHOW_SHOTS when it names a folder.
@MainActor
final class ShowUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen]
        app.launch()
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["SHOW_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    private func any(_ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    private func text(_ fragment: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] %@", fragment)).firstMatch
    }

    private func openSheet() {
        let card = any("showCard")
        XCTAssertTrue(card.waitForExistence(timeout: 15), "the card shows while the voice reports")
        XCTAssertTrue(card.label.contains("Showing: pricing.py · edited 40–42 · 1 failing test"), card.label)
        card.tap()
        XCTAssertTrue(app.navigationBars["Showing"].waitForExistence(timeout: 5), "the sheet opens")
    }

    func testTheCardOpensTheSheetAtTheArtifactTheVoiceNames() throws {
        launch("showing")
        openSheet()
        XCTAssertTrue(any("showTab-edit-pricing.py").isSelected, "follows current")
        XCTAssertTrue(text("lines 40–42").waitForExistence(timeout: 5))
        XCTAssertTrue(text("for attempt in range(retries):").waitForExistence(timeout: 5), "the edited lines are on screen")
        shot("show-file")
    }

    func testTabsSwitchBetweenFileDiffAndTest() throws {
        launch("showing")
        openSheet()
        app.buttons["Diff"].firstMatch.tap()
        XCTAssertTrue(text("+    for attempt in range(retries):").waitForExistence(timeout: 5), "the diff")
        shot("show-diff")
        any("showTab-test-test output").tap()
        XCTAssertTrue(any("showTab-test-test output").isSelected)
        XCTAssertTrue(text("AssertionError: assert 90 == 80").waitForExistence(timeout: 5), "the test output")
        XCTAssertTrue(text("uv run pytest -q tests/test_pricing.py").exists, "the command")
        shot("show-test")
        any("showTab-read-test_pricing.py").tap()
        XCTAssertTrue(any("showChanged").waitForExistence(timeout: 5), "changed since it was spoken about")
        any("showTab-edit-.env").tap()
        XCTAssertTrue(text("a hidden file: not shown").waitForExistence(timeout: 5), "a refused file shows its reason, never content")
    }

    func testPinAndShownEarlier() throws {
        launch("showing")
        openSheet()
        any("showPin").tap()
        XCTAssertTrue(app.buttons["Pinned"].waitForExistence(timeout: 3))
        any("showTab-test-test output").tap()
        XCTAssertTrue(any("showTab-edit-pricing.py").isSelected, "a pin outranks a tap")
        any("showPin").tap()
        XCTAssertTrue(app.buttons["Pin"].waitForExistence(timeout: 3))
        XCTAssertTrue(any("showEarlier").exists)
        XCTAssertTrue(text("Shown earlier").exists)
        text("changelog.md · edited 3–9").tap()
        app.buttons["changelog.md"].firstMatch.tap()
        XCTAssertTrue(text("no longer there").waitForExistence(timeout: 5), "an earlier artifact, pinned, renders")
    }

    func testOffOnThisPhoneShowsNoCard() throws {
        launch("showingOff")
        XCTAssertTrue(app.buttons["Settings"].waitForExistence(timeout: 15))
        XCTAssertFalse(any("showCard").exists)
    }

    func testTurningItOffHidesTheCardAndTurningItOnNeedsTheOwner() throws {
        launch("showing")
        XCTAssertTrue(any("showCard").waitForExistence(timeout: 15))
        app.settingsItem("showSettingItem", .button).tap()
        XCTAssertTrue(text("Code stays on your Mac unless you turn this on.").waitForExistence(timeout: 5), "the help")
        let toggle = app.switches["showSetting"].firstMatch
        XCTAssertEqual(toggle.value as? String, "1")
        toggle.switches.firstMatch.tap()
        XCTAssertTrue(NSPredicate(format: "value == '0'").evaluate(with: toggle) || toggle.value as? String == "0")
        shot("show-setting")
        app.buttons["Done"].firstMatch.tap()
        XCTAssertTrue(any("showCard").waitForNonExistence(timeout: 5), "off: no card")
        // On again needs Face ID or the passcode; the simulator has neither enrolled, so it stays off.
        app.settingsItem("showSettingItem", .button).tap()
        let again = app.switches["showSetting"].firstMatch
        XCTAssertTrue(again.waitForExistence(timeout: 5))
        again.switches.firstMatch.tap()
        sleep(2)
        if app.alerts.firstMatch.exists { app.alerts.firstMatch.buttons.firstMatch.tap() }
        XCTAssertEqual(app.switches["showSetting"].firstMatch.value as? String, "0", "not turned on without the owner")
    }

    /// Against a real test daemon over the pinned link, driven by apps/ios/e2e/show_ui.py through cue files in
    /// TEST_RUNNER_SHOW_LIVE. Skipped otherwise.
    func testShowLive() throws {
        let env = ProcessInfo.processInfo.environment
        guard let folder = env["SHOW_LIVE"] else { throw XCTSkip("live: run apps/ios/e2e/show_ui.py") }
        func cue(_ name: String) { FileManager.default.createFile(atPath: "\(folder)/cue-\(name)", contents: Data()) }
        func wait(_ name: String, _ timeout: TimeInterval) -> Bool {
            let deadline = Date().addingTimeInterval(timeout)
            while Date() < deadline {
                if FileManager.default.fileExists(atPath: "\(folder)/go-\(name)") { return true }
                Thread.sleep(forTimeInterval: 0.5)
            }
            return false
        }
        func live(_ name: String) {
            try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
        }
        app = XCUIApplication()
        app.launchEnvironment["POINTE_PAIR"] = try XCTUnwrap(env["POINTE_PAIR"], "set TEST_RUNNER_POINTE_PAIR")
        app.launch()
        XCTAssertTrue(app.buttons["Settings"].waitForExistence(timeout: 30), "paired, on the call screen")
        cue("ready")

        XCTAssertTrue(wait("reported-off", 150), "the driver's report")
        XCTAssertFalse(any("showCard").waitForExistence(timeout: 6), "off on this phone: no card while the Mac shows it")
        live("live-off")
        cue("checked-off")

        XCTAssertTrue(wait("on", 60))
        let card = any("showCard")
        XCTAssertTrue(card.waitForExistence(timeout: 20), "on: the card")
        XCTAssertTrue(card.label.contains("pricing.py · edited 41"), card.label)
        card.tap()
        XCTAssertTrue(app.navigationBars["Showing"].waitForExistence(timeout: 5))
        any("showTab-edit-pricing.py").tap()
        XCTAssertTrue(text("gold pays 80%").waitForExistence(timeout: 10), "the edited line, read from the Mac")
        live("live-file")
        any("showTab-test-test output").tap()
        XCTAssertTrue(text("AssertionError: assert 100 == 80").waitForExistence(timeout: 10), "the failing assertion")
        live("live-test")
        cue("done")
    }
}
