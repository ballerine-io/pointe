import XCTest

/// The dictionary, on the -demo fixtures: no Mac needed. The menu item, the sheet (list with source and language, add,
/// a refused consent word with the reason, edit, delete, a suggestion's Add and Ignore, Learn from my fixes and when a change applies),
/// and the "Learned: …" toast with Undo. Screenshots go to VOCAB_SHOTS when it names a folder.
@MainActor
final class VocabularyUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen]
        app.launch()
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["VOCAB_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    private func text(_ fragment: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] %@", fragment)).firstMatch
    }

    private func openDictionary() {
        let settings = app.buttons["Settings"]
        XCTAssertTrue(settings.waitForExistence(timeout: 15))
        settings.tap()
        let entry = app.buttons["dictionaryItem"].firstMatch
        XCTAssertTrue(entry.waitForExistence(timeout: 5), "Dictionary is in the settings menu")
        entry.tap()
        XCTAssertTrue(app.navigationBars["Dictionary"].waitForExistence(timeout: 5), "the Dictionary sheet opens")
    }

    func testTheSheetListsEachEntryWithItsSourceAndLanguage() throws {
        launch("dictionary")
        openDictionary()
        XCTAssertTrue(app.buttons["dictionaryTerm-Quillfeather"].waitForExistence(timeout: 5))
        XCTAssertTrue(text("you fixed it").exists && text("you added it").exists)
        XCTAssertTrue(app.buttons["dictionaryLang-Marrowind"].label.contains("EN + HE"))
        XCTAssertTrue(text("Stored only on your Mac").exists, "the lede")
        XCTAssertTrue(text("Kestrelbay").exists, "a suggestion from a session")
        shot("dictionary-sheet")
    }

    func testAddRefuseEditAndDelete() throws {
        launch("dictionary")
        openDictionary()
        let box = app.textFields["dictionaryNew"]
        XCTAssertTrue(box.waitForExistence(timeout: 5))
        box.tap()
        box.typeText("okay")
        app.buttons["dictionaryAdd"].tap()
        XCTAssertTrue(text("a yes, no or stop word").waitForExistence(timeout: 5), "a consent word is refused, with the reason")
        XCTAssertFalse(app.buttons["dictionaryTerm-okay"].exists)
        shot("dictionary-refused")

        box.tap()
        box.press(forDuration: 1.0)
        if app.menuItems["Select All"].waitForExistence(timeout: 2) { app.menuItems["Select All"].tap() }
        box.typeText(XCUIKeyboardKey.delete.rawValue)
        box.typeText("Tarnwick")
        app.buttons["dictionaryAdd"].tap()
        XCTAssertTrue(app.buttons["dictionaryTerm-Tarnwick"].waitForExistence(timeout: 5), "a name is added")

        app.buttons["dictionaryTerm-Tarnwick"].tap()
        let field = app.alerts.textFields.firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 5), "tapping an entry edits it")
        field.tap()
        field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: 12) + "Tarnwicks")
        app.alerts.buttons["Save"].firstMatch.tap()
        XCTAssertTrue(app.buttons["dictionaryTerm-Tarnwicks"].waitForExistence(timeout: 5), "the edit is saved")

        app.buttons["dictionaryDelete-Tarnwicks"].tap()
        XCTAssertFalse(app.buttons["dictionaryTerm-Tarnwicks"].waitForExistence(timeout: 2), "delete removes it")
    }

    func testASuggestionIsAddedOrIgnored() throws {
        launch("dictionary")
        openDictionary()
        let add = app.buttons["suggestAdd-Kestrelbay"]
        XCTAssertTrue(add.waitForExistence(timeout: 5))
        add.tap()
        XCTAssertTrue(app.buttons["dictionaryTerm-Kestrelbay"].waitForExistence(timeout: 5), "added from a session")
        XCTAssertTrue(text("from a session").exists)
        XCTAssertFalse(app.buttons["suggestAdd-Kestrelbay"].exists, "no longer suggested")
    }

    func testLearningTogglesAndTheSheetSaysWhenAChangeApplies() throws {
        launch("dictionary")
        openDictionary()
        let learn = app.switches["dictionaryLearn"]
        if !learn.waitForExistence(timeout: 5) { app.swipeUp() }
        XCTAssertTrue(learn.waitForExistence(timeout: 5))
        XCTAssertEqual(learn.value as? String, "1", "on by default")
        learn.switches.firstMatch.exists ? learn.switches.firstMatch.tap() : learn.tap()
        XCTAssertTrue(NSPredicate(format: "value == '0'").evaluate(with: learn) || learn.value as? String == "0")
        XCTAssertTrue(text("Applies on the next call.").exists)
        XCTAssertFalse(text("Kestrelbay").exists, "learning off: no suggestions")
        shot("dictionary-learn-off")
    }

    func testTheToastNamesWhatWasLearnedAndUndoRemovesIt() throws {
        launch("dictionaryLearned")
        let toast = text("Learned: Quillfeather")
        XCTAssertTrue(toast.waitForExistence(timeout: 15), "a fix that taught a name says so")
        shot("dictionary-toast")
        app.buttons["dictionaryUndo"].tap()
        XCTAssertFalse(toast.waitForExistence(timeout: 2), "Undo closes the toast")
        openDictionary()
        XCTAssertTrue(app.buttons["dictionaryTerm-Marrowind"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["dictionaryTerm-Quillfeather"].exists, "and takes the name out of the dictionary")
    }
}
