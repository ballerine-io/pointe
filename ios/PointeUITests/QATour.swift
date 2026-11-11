import XCTest

/// A walk through every control against a real test daemon, saving a screenshot of each state. Runs only when
/// TEST_RUNNER_QA_SHOTS names a folder; the daemon side registers sessions and holds a permission request on cue.
@MainActor
final class QATour: XCTestCase {
    private var shots = ""
    private var app: XCUIApplication!

    private func shot(_ name: String) {
        let data = XCUIScreen.main.screenshot().pngRepresentation
        try? data.write(to: URL(fileURLWithPath: "\(shots)/\(name).png"))
    }

    private func cue(_ name: String) {
        FileManager.default.createFile(atPath: "\(shots)/cue-\(name)", contents: Data())
    }

    private func text(_ fragment: String) -> XCUIElement {
        app.staticTexts.containing(NSPredicate(format: "label CONTAINS[c] %@", fragment)).firstMatch
    }

    func testTour() throws {
        let env = ProcessInfo.processInfo.environment
        guard let folder = env["QA_SHOTS"], let link = env["POINTE_PAIR"] else { throw XCTSkip("QA tour: set TEST_RUNNER_QA_SHOTS") }
        shots = folder
        app = XCUIApplication()
        app.launchEnvironment["POINTE_PAIR"] = link
        app.launch()

        let connect = app.buttons["Connect"]
        XCTAssertTrue(connect.waitForExistence(timeout: 30), "paired, shows Connect")
        shot("00-before-connect")
        connect.tap()
        XCTAssertTrue(app.buttons["Hang up"].waitForExistence(timeout: 30), "the call is up")
        sleep(2)
        app.buttons["Mute"].tap()  // the simulator hears the Mac's room: typing drives this tour
        sleep(5)  // the greeting
        shot("01-live")

        // Orchestrator: the status line counts sessions; no single session is singled out.
        let line = app.descendants(matching: .any)["statusLine"]
        XCTAssertTrue(line.waitForExistence(timeout: 10))
        XCTAssertTrue(line.label.contains("Orchestrating"), "orchestrator status line: \(line.label)")

        // Typing
        app.buttons["Type"].tap()
        let field = app.descendants(matching: .any)["typeField"]
        XCTAssertTrue(field.waitForExistence(timeout: 5), "the type bar opens")
        field.tap()
        field.typeText("What is two plus two? Answer in one word.\n")
        XCTAssertTrue(text("two plus two").waitForExistence(timeout: 10), "the typed turn shows")
        XCTAssertTrue(text("four").waitForExistence(timeout: 30) || text("4").exists, "the bot answers the typed question")
        shot("02-typed")
        app.buttons["Type"].tap()  // close the keyboard bar

        // Tap to correct
        text("two plus two").tap()
        XCTAssertTrue(app.navigationBars["Fix it"].waitForExistence(timeout: 5), "the fix sheet opens")
        let editor = app.descendants(matching: .any)["fixField"]
        XCTAssertTrue(editor.waitForExistence(timeout: 5))
        editor.tap()
        let current = (editor.value as? String) ?? ""
        editor.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: current.count + 5))
        editor.typeText("What is three plus three? Answer in one word.")
        shot("03-fix-sheet")
        app.navigationBars["Fix it"].buttons["Send"].tap()
        XCTAssertTrue(text("three plus three").waitForExistence(timeout: 10), "the corrected turn shows")
        XCTAssertTrue(text("six").waitForExistence(timeout: 30) || text("6").exists, "the bot answers the corrected words")
        XCTAssertTrue(text("edited").exists, "marked edited")
        shot("04-corrected")

        // Clean up my words
        app.buttons["Settings"].tap()
        let cleanup = app.switches["Clean up my words"].exists ? app.switches["Clean up my words"] : app.buttons["Clean up my words"]
        XCTAssertTrue(cleanup.waitForExistence(timeout: 5))
        cleanup.tap()
        sleep(1)

        // Brainstorm
        app.buttons["Brainstorm"].tap()
        XCTAssertTrue(app.buttons["Back to conversation"].waitForExistence(timeout: 10), "brainstorm panel")
        sleep(1)
        shot("05-brainstorm")
        app.buttons["Back to conversation"].tap()
        XCTAssertTrue(app.buttons["Brainstorm"].waitForExistence(timeout: 10), "back in the conversation")
        sleep(4)
        shot("06-back-from-brainstorm")

        // Focus on one session, then back to all
        let alpha = app.buttons.containing(NSPredicate(format: "label BEGINSWITH %@", "alpha")).firstMatch
        XCTAssertTrue(alpha.waitForExistence(timeout: 5))
        alpha.tap()
        XCTAssertTrue(app.descendants(matching: .any).containing(NSPredicate(format: "label CONTAINS %@", "Focused on alpha")).firstMatch
            .waitForExistence(timeout: 10), "session mode, focused")
        shot("07-focused")
        app.buttons.containing(NSPredicate(format: "label BEGINSWITH %@", "All sessions")).firstMatch.tap()
        XCTAssertTrue(app.descendants(matching: .any).containing(NSPredicate(format: "label CONTAINS %@", "Orchestrating")).firstMatch
            .waitForExistence(timeout: 10), "back to orchestrator")
        shot("08-orchestrating")

        // Sessions sheet: swipe to disconnect gamma
        app.buttons["Sessions"].tap()
        XCTAssertTrue(app.navigationBars["Sessions"].waitForExistence(timeout: 5))
        shot("09-sessions-sheet")
        let gamma = app.cells.containing(NSPredicate(format: "label CONTAINS %@", "gamma")).firstMatch
        if gamma.waitForExistence(timeout: 5) {
            gamma.swipeLeft()
            shot("09b-swiped")
            if app.buttons["Disconnect"].waitForExistence(timeout: 3) { app.buttons["Disconnect"].tap() }
        }
        sleep(2)
        shot("09c-after-disconnect")
        XCTAssertFalse(app.cells.containing(NSPredicate(format: "label CONTAINS %@", "gamma")).firstMatch.exists, "gamma is off the voice")
        app.navigationBars["Sessions"].buttons["Done"].tap()

        // Scroll up: new lines must not move the view; a "New" pill appears
        cue("more-talk")  // a conversation long enough to scroll
        XCTAssertTrue(text("Canada").waitForExistence(timeout: 40))
        sleep(8)
        let scroll = app.scrollViews["conversation"]
        scroll.swipeDown(velocity: .slow); scroll.swipeDown(velocity: .slow); scroll.swipeDown(velocity: .slow)
        let topText = app.staticTexts.element(boundBy: 6).label
        shot("10a-scrolled-up")
        cue("even-more-talk")  // the driver types more while the user reads above
        XCTAssertTrue(app.buttons["New"].waitForExistence(timeout: 40), "the New pill shows while scrolled up")
        sleep(10)
        XCTAssertTrue(app.staticTexts[topText].isHittable, "scrolled up, the view did not move with the new lines")
        shot("10-new-pill")
        app.buttons["New"].tap()
        sleep(1)
        shot("11-back-at-bottom")

        // A held request
        cue("request")
        let deny = app.buttons["Deny"]
        XCTAssertTrue(deny.waitForExistence(timeout: 60), "the request card shows")
        sleep(1)  // it slides in
        shot("12-request")
        deny.tap()
        XCTAssertTrue(deny.waitForNonExistence(timeout: 15), "answered")

        app.buttons["Hang up"].tap()
        XCTAssertTrue(connect.waitForExistence(timeout: 15), "hung up")
        shot("13-hung-up")
    }
}
