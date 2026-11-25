import XCTest

/// The approvals record (docs/features/approvals-record.md), on the -demo fixtures: no Mac needed. Settings has its
/// row; the sheet lists every approval of the demo's record, newest first, and each row is read with how it was given,
/// when, the exact request and the voice lock's score. Screenshots go to APPROVALS_SHOTS.
@MainActor
final class ApprovalsUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func launch(_ more: [String] = [], dark: Bool = false) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", "call", "-demoEnglish", "-pointe.theme", dark ? "dark" : "light"] + more
        app.launch()
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["APPROVALS_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    private func row(_ id: String) -> XCUIElement { app.descendants(matching: .any)["approval.\(id)"].firstMatch }

    func testSettingsOpensTheRecordAndEveryApprovalIsARow() {
        launch()
        let item = app.settingsItem("approvalsItem")
        XCTAssertTrue(item.exists, "Settings has the approvals record")
        XCTAssertEqual(item.label, "Approvals record")
        item.tap()
        XCTAssertTrue(row("p5").waitForExistence(timeout: 10), "the record opens")
        let list = app.collectionViews.firstMatch
        var seen: [String] = []
        for id in ["p5", "p4", "p3", "p2", "p1"] {
            for _ in 0..<5 where !row(id).exists { list.swipeUp(velocity: .slow) }
            XCTAssertTrue(row(id).exists, "\(id) is in the record")
            seen.append(id)
        }
        XCTAssertEqual(seen.count, 5, "every approval of the journal is a row")
    }

    func testARowIsReadWithHowWhenTheExactRequestAndTheScore() {
        for dark in [false, true] {
            launch(["-sheet", "approvals"], dark: dark)
            XCTAssertTrue(row("p5").waitForExistence(timeout: 15))
            XCTAssertTrue(row("p5").label.hasPrefix("Approved by voice, harbor, 21 Nov, 08:00, Bash"), row("p5").label)
            XCTAssertTrue(row("p5").label.hasSuffix("Voice lock commands: score 0.64"), row("p5").label)
            XCTAssertTrue(row("p4").label.hasSuffix("Voice lock off: the voice was not checked"), row("p4").label)
            XCTAssertTrue(row("p3").label.hasPrefix("Approved from a notification, docs on devbox"), row("p3").label)
            shot("iphone-approvals-\(dark ? "dark" : "light")")
            let list = app.collectionViews.firstMatch
            for _ in 0..<5 where !row("p1").exists { list.swipeUp(velocity: .slow) }
            XCTAssertTrue(row("p2").label.hasPrefix("Denied by a tap"), row("p2").label)
            XCTAssertFalse(row("p2").label.contains("Voice lock"), "a tap has no voice to score")
            XCTAssertTrue(row("p1").label.contains("git push --force-with-lease origin retry-fix"), "the request, word for word")
            XCTAssertFalse(app.buttons["Approve"].exists || app.buttons["Deny"].exists, "the record answers nothing")
            app.terminate()
        }
    }
}
