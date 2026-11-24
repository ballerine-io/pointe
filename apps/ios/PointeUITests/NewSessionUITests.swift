import XCTest

/// Starting a new session (docs/design/new-session.md), on the -demo fixtures. No Mac needed, and no Face ID: these
/// stop before Start is tapped.
@MainActor
final class NewSessionUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen]
        app.launch()
    }

    private func any(_ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    func testTheSessionsSheetOpensNewSessionWithItsFieldsAndStart() {
        launch("sessions")
        XCTAssertTrue(app.navigationBars["Sessions"].waitForExistence(timeout: 15))
        let open = app.buttons["newSession"]
        XCTAssertTrue(open.waitForExistence(timeout: 5), "New session is in the Sessions sheet")
        XCTAssertEqual(open.label, "New session")
        open.tap()

        XCTAssertTrue(app.navigationBars["New session"].waitForExistence(timeout: 10))
        // longer than an identifier query takes (128 characters): matched by its label
        let lede = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "Starts a coding agent in a folder you already work in.")).firstMatch
        XCTAssertTrue(lede.waitForExistence(timeout: 5))
        XCTAssertTrue(lede.label.hasSuffix("asks before it acts, as every session does."), lede.label)
        let claude = any("newSessionAgent.claude-code"), codex = any("newSessionAgent.codex")
        XCTAssertTrue(claude.waitForExistence(timeout: 5), "the agents the Mac offers")
        XCTAssertTrue(claude.isSelected, "the first agent that can start is picked")
        XCTAssertFalse(codex.isEnabled, "an agent that is not installed cannot be picked")
        XCTAssertTrue(codex.label.contains("Codex is not installed on this Mac."), "and says why: \(codex.label)")
        XCTAssertTrue(any("newSessionClaudeNote").exists, "Claude Code says where it opens")
        XCTAssertTrue(any("newSessionMachine.studio").exists)
        XCTAssertFalse(any("newSessionMachine.devbox").isEnabled, "a start runs on this Mac only")
        let shop = any("newSessionFolder.shop")
        XCTAssertTrue(shop.exists && shop.isSelected)
        XCTAssertTrue(shop.label.contains("/Users/mira/work/shop"), "a folder shows its path: \(shop.label)")

        let start = app.buttons["newSessionStart"]
        XCTAssertTrue(start.exists && start.isEnabled, "Start is there, and offered")
        XCTAssertEqual(start.label, "Start")
        XCTAssertTrue(app.buttons["newSessionCancel"].exists)

        app.swipeUp()  // the two optional fields are under the folders
        XCTAssertTrue(any("newSessionName").waitForExistence(timeout: 5))
        XCTAssertEqual(any("newSessionName").placeholderValue, "Same as the folder")
        XCTAssertTrue(any("newSessionPrompt").exists)

        app.buttons["newSessionCancel"].tap()
        XCTAssertTrue(app.navigationBars["New session"].waitForNonExistence(timeout: 5))
        XCTAssertTrue(app.navigationBars["Sessions"].exists, "Cancel goes back to the sessions, and starts nothing")
    }

    func testStartingRowsShowUnderTheSessions() {
        launch("newSession")
        XCTAssertTrue(app.navigationBars["Sessions"].waitForExistence(timeout: 15))
        let starting = any("starting.shop-2"), failed = any("starting.lantern")
        if !starting.waitForExistence(timeout: 5) { app.swipeUp() }
        XCTAssertTrue(starting.waitForExistence(timeout: 5))
        XCTAssertTrue(starting.label.contains("Claude Code") && starting.label.contains("starting"), starting.label)
        XCTAssertTrue(failed.label.contains("did not start") && failed.label.contains("Codex's daemon is not running."), failed.label)
    }

    func testAReadBackShowsAsACardAndCancelNeedsNoFaceID() {
        launch("startPending")
        let cancel = app.buttons["startCancel"]
        XCTAssertTrue(cancel.waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts["Start this session?"].exists)
        XCTAssertTrue(app.staticTexts["Start a Claude Code session in shop on studio, named shop-2? Say yes or tap."].exists, "the exact read-back")
        XCTAssertEqual(app.buttons["startConfirm"].label, "Start")
        cancel.tap()
        XCTAssertTrue(cancel.waitForNonExistence(timeout: 5), "Cancel drops it at once")
    }
}
