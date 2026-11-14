import XCTest

/// Brain dump on the -demo fixtures: no Mac needed. The panel while dumping (every thought, the live line, Done, Discard),
/// Done opening the review with the structured prompt, Send in two taps, Add more, and the bar's button. Screenshots go to
/// DUMP_SHOTS when it names a folder.
@MainActor
final class BrainDumpUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen]
        app.launch()
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["DUMP_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    private func any(_ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    private func text(_ fragment: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] %@", fragment)).firstMatch
    }

    func testWhileDumpingEveryThoughtShowsAndNothingElseAsks() {
        launch("brainDump")
        XCTAssertTrue(any("dump.panel").waitForExistence(timeout: 15))
        XCTAssertEqual(any("dump.title").label, "Brain dump")
        XCTAssertTrue(text("Talk freely. Nothing is sent until you say so.").exists)
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "dump.thought").count, 3, "every thought, not a 600-character tail")
        XCTAssertTrue(text("So the checkout keeps timing out").exists)
        XCTAssertTrue(text("We must not touch the tax service").exists)
        XCTAssertTrue(text("and maybe the cache should live per merchant").exists, "the live hearing line")
        XCTAssertTrue(app.staticTexts["Brain dump"].exists, "the state line")
        XCTAssertEqual(any("dump.done").label, "Done")
        XCTAssertEqual(app.buttons["Done"].exists, true, "the bar's button reads Done while dumping")
        XCTAssertFalse(app.buttons["Approve"].exists)
        XCTAssertTrue(app.buttons["Mute"].isHittable, "the mic stays reachable")
        shot("dump-1-dumping")
    }

    func testDoneOpensTheReviewAndSendTakesTwoTaps() {
        launch("brainDump")
        XCTAssertTrue(any("dump.done").waitForExistence(timeout: 15))
        any("dump.done").tap()
        XCTAssertTrue(any("dump.review").waitForExistence(timeout: 10), "the review sheet")
        XCTAssertTrue(app.staticTexts["Your brain dump, structured"].exists)
        XCTAssertTrue(text("In your words. Edit it, add more, or send it to a session.").exists)
        let editor = any("dump.text")
        XCTAssertTrue(editor.exists)
        XCTAssertTrue((editor.value as? String ?? "").contains("Goal: So the checkout keeps timing out"), editor.value as? String ?? "")
        let send = any("dump.send")
        XCTAssertEqual(send.label, "Send to billing/main", "the active session is preselected")
        shot("dump-2-review")
        send.tap()
        XCTAssertEqual(send.label, "Send to billing/main?", "the first tap asks")
        send.tap()
        XCTAssertTrue(app.buttons["Brain dump"].waitForExistence(timeout: 5), "sent: the dump is gone and the bar offers a new one")
        XCTAssertFalse(any("dump.review").exists)
        shot("dump-3-sent")
    }

    func testTheReviewFixtureShowsTheStructuredPromptAndAddMoreReopensTheDump() {
        launch("brainDumpReview")
        XCTAssertTrue(any("dump.review").waitForExistence(timeout: 15))
        let value = any("dump.text").value as? String ?? ""
        for part in ["Goal: stop the checkout timing out", "Context:", "Constraints:", "- we must not touch the tax service", "Open questions:"] {
            XCTAssertTrue(value.contains(part), "\(part) in \(value)")
        }
        XCTAssertTrue(text("Or say “send it to …”, “add more”, “read it back” or “discard”.").exists)
        XCTAssertEqual(any("dump.more").label, "Add more")
        any("dump.more").tap()
        XCTAssertTrue(any("dump.panel").waitForExistence(timeout: 5), "back to dumping, the thoughts kept")
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "dump.thought").count, 3)
    }

    func testDiscardAsksFirstAndCloseLeavesReviewInTheBar() {
        launch("brainDumpReview")
        XCTAssertTrue(any("dump.review").waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons["Close"].waitForExistence(timeout: 5))
        app.buttons["Close"].tap()
        XCTAssertTrue(app.buttons["Review"].waitForExistence(timeout: 5), "the bar's button reopens the review")
        app.buttons["Review"].tap()
        XCTAssertTrue(any("dump.discard").waitForExistence(timeout: 5))
        any("dump.discard").tap()
        XCTAssertEqual(any("dump.discard").label, "Discard the dump?", "the first tap asks")
        any("dump.discard").tap()
        XCTAssertTrue(app.buttons["Brain dump"].waitForExistence(timeout: 5), "gone: the bar offers a new one")
        XCTAssertFalse(any("dump.review").exists)
    }
}
