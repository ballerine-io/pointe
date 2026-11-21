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

    /// Puts the keyboard away (Type closes the type bar): with the room back the card is whole, its buttons in reach.
    private func keyboardDown() {
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 10), "typing comes forward first")
        app.buttons["Type"].tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 5))
    }

    /// Opens the notes when the card is folded (the keyboard is up, and the card does not fit above it).
    private func showNotes() {
        let toggle = app.buttons["whisperNotes"]
        if toggle.waitForExistence(timeout: 3), toggle.label == WhisperCopyWords.showNotes { toggle.tap() }
    }

    func testWhisperModeShowsTheCardAndBringsTypingForward() throws {
        launch("whisper")
        XCTAssertTrue(app.otherElements["whisperCard"].waitForExistence(timeout: 15) || text("Whisper mode").exists)
        showNotes()
        XCTAssertTrue(text("Whisper recognition is limited").waitForExistence(timeout: 3))
        XCTAssertTrue(text("A whispered yes may not match it").exists, "the voice-lock note")
        XCTAssertTrue(text("Whisper works best with Push to talk").exists)
        let field = app.textFields["typeField"].exists ? app.textFields["typeField"] : app.textViews["typeField"]
        XCTAssertTrue(field.waitForExistence(timeout: 5), "typing is shown by default")
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5), "with the keyboard up")
        shot("whisper-on")
    }

    func testNotNowThenBackToNormal() throws {
        launch("whisper")
        XCTAssertTrue(app.otherElements["whisperCard"].waitForExistence(timeout: 15))
        keyboardDown()
        let notNow = app.buttons["whisperNotNow"]
        XCTAssertTrue(notNow.waitForExistence(timeout: 5))
        notNow.tap()
        XCTAssertFalse(text("Whisper works best with Push to talk").waitForExistence(timeout: 1), "the suggestion goes away")
        XCTAssertTrue(app.buttons["whisperOff"].exists)
        app.buttons["whisperOff"].tap()
        XCTAssertTrue(app.buttons["whisperOff"].waitForNonExistence(timeout: 5), "back to normal: the card goes")
        shot("whisper-off")
    }

    func testTurnOnPushToTalkFromTheSuggestion() throws {
        launch("whisper")
        XCTAssertTrue(app.otherElements["whisperCard"].waitForExistence(timeout: 15))
        keyboardDown()
        let ptt = app.buttons["whisperPushToTalk"]
        XCTAssertTrue(ptt.waitForExistence(timeout: 5))
        ptt.tap()
        XCTAssertTrue(ptt.waitForNonExistence(timeout: 5), "push to talk is on: no suggestion")
        XCTAssertTrue(app.buttons["whisperOff"].exists, "whisper mode stays on")
    }

    /// With the keyboard up the card does not fit above the type bar: it folds to its title and Show notes, all of it
    /// above the type bar, and opens on a tap.
    func testWithTheKeyboardUpTheCardFoldsToItsTitle() throws {
        launch("whisper")
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 15), "the keyboard is up")
        let toggle = app.buttons["whisperNotes"]
        XCTAssertTrue(toggle.waitForExistence(timeout: 5), "folded: Show notes")
        XCTAssertEqual(toggle.label, WhisperCopyWords.showNotes)
        XCTAssertFalse(text("Whisper recognition is limited").exists, "the notes are folded away")
        let field = app.textFields["typeField"].exists ? app.textFields["typeField"] : app.textViews["typeField"]
        let title = app.staticTexts["Whisper mode"]
        XCTAssertTrue(title.exists, "the folded title")
        XCTAssertLessThanOrEqual(title.frame.maxY, field.frame.minY, "the folded card's line is above the type bar")
        XCTAssertGreaterThanOrEqual(title.frame.minY, app.descendants(matching: .any)["statusLine"].firstMatch.frame.maxY, "and under the header")
        XCTAssertTrue(toggle.isHittable)
        shot("whisper-folded")
        toggle.tap()
        XCTAssertTrue(text("Whisper recognition is limited").waitForExistence(timeout: 3), "the notes, on a tap")
        XCTAssertEqual(toggle.label, WhisperCopyWords.hideNotes)
    }

    func testSettingsTurnsWhisperModeOn() throws {
        launch("whisperOff")
        XCTAssertFalse(app.buttons["whisperOff"].exists)
        XCTAssertTrue(app.settingsItem("whisperItem", .switch).waitForExistence(timeout: 5), "Whisper is in Settings")
        app.flipSetting("whisperItem")
        app.closeSettings()
        XCTAssertTrue(app.otherElements["whisperCard"].waitForExistence(timeout: 5), "the card shows")
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5), "typing comes forward")
        shot("whisper-menu")
    }
}

/// The toggle's words (WhisperCopy in the app target, which UI tests do not import).
enum WhisperCopyWords {
    static let showNotes = "Show notes"
    static let hideNotes = "Hide notes"
}
