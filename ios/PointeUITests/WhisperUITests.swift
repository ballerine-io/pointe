import XCTest

/// Whisper mode, on the -demo fixtures: no Mac needed. The card with its notes, typing forward with the keyboard up,
/// the larger caption, Not now, Turn on, Back to normal, and the Settings menu toggle. Screenshots go to WHISPER_SHOTS.
@MainActor
final class WhisperUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen]
        app.launch()
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["WHISPER_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    private func text(_ fragment: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] %@", fragment)).firstMatch
    }

    func testWhisperModeShowsTheCardAndBringsTypingForward() throws {
        launch("whisper")
        XCTAssertTrue(app.otherElements["whisperCard"].waitForExistence(timeout: 15) || text("short, quiet replies").exists)
        XCTAssertTrue(text("Whisper recognition is limited").exists)
        XCTAssertTrue(text("A whispered yes may not match it").exists, "the voice-lock note")
        XCTAssertTrue(text("Whisper works best with Push to talk").exists)
        let field = app.textFields["typeField"].exists ? app.textFields["typeField"] : app.textViews["typeField"]
        XCTAssertTrue(field.waitForExistence(timeout: 5), "typing is shown by default")
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5), "with the keyboard up")
        shot("whisper-on")
    }

    func testNotNowThenBackToNormal() throws {
        launch("whisper")
        let notNow = app.buttons["whisperNotNow"]
        XCTAssertTrue(notNow.waitForExistence(timeout: 15))
        notNow.tap()
        XCTAssertFalse(text("Whisper works best with Push to talk").waitForExistence(timeout: 1), "the suggestion goes away")
        XCTAssertTrue(app.buttons["whisperOff"].exists)
        app.buttons["whisperOff"].tap()
        XCTAssertTrue(app.buttons["whisperOff"].waitForNonExistence(timeout: 5), "back to normal: the card goes")
        shot("whisper-off")
    }

    func testTurnOnPushToTalkFromTheSuggestion() throws {
        launch("whisper")
        let ptt = app.buttons["whisperPushToTalk"]
        XCTAssertTrue(ptt.waitForExistence(timeout: 15))
        ptt.tap()
        XCTAssertTrue(ptt.waitForNonExistence(timeout: 5), "push to talk is on: no suggestion")
        XCTAssertTrue(app.buttons["whisperOff"].exists, "whisper mode stays on")
    }

    func testTheSettingsMenuTurnsWhisperModeOn() throws {
        launch("whisperOff")
        let settings = app.buttons["Settings"]
        XCTAssertTrue(settings.waitForExistence(timeout: 15))
        XCTAssertFalse(app.buttons["whisperOff"].exists)
        settings.tap()
        let item = app.switches["whisperItem"].exists ? app.switches["whisperItem"] : app.buttons["whisperItem"]
        XCTAssertTrue(item.waitForExistence(timeout: 5), "Whisper is in the settings menu")
        item.tap()
        XCTAssertTrue(app.buttons["whisperOff"].waitForExistence(timeout: 5), "the card shows")
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5), "typing comes forward")
        shot("whisper-menu")
    }
}
