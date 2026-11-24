import XCTest

/// Driven by apps/ios/e2e/conflict_ui.py: a test daemon with two sessions that disagree. The link comes in
/// TEST_RUNNER_POINTE_CONFLICT_PAIR; without it this test is skipped, so the demo-only passes stay offline.
@MainActor
final class ConflictLiveUITests: XCTestCase {
    func testAConflictOnAPairedMac() throws {
        guard let link = ProcessInfo.processInfo.environment["POINTE_CONFLICT_PAIR"] else {
            throw XCTSkip("run by apps/ios/e2e/conflict_ui.py")
        }
        let app = XCUIApplication()
        app.launchEnvironment["POINTE_PAIR"] = link
        app.launch()
        let connect = app.buttons["Connect"]
        XCTAssertTrue(connect.waitForExistence(timeout: 30), "the app paired and shows Connect")
        connect.tap()
        XCTAssertTrue(app.buttons["hangUp"].waitForExistence(timeout: 20), "the call is up")
        let mute = app.buttons["Turn mic off"]
        if mute.waitForExistence(timeout: 5) { mute.tap() }  // the simulator hears the Mac's microphone

        let card = app.descendants(matching: .any)["conflictCard"].firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 180), "the conflict card shows")
        let claimA = app.descendants(matching: .any)["conflictClaimA"].firstMatch
        let claimB = app.descendants(matching: .any)["conflictClaimB"].firstMatch
        XCTAssertTrue(claimA.label.contains("lantern") && claimA.label.contains("passed"), claimA.label)
        XCTAssertTrue(claimB.label.contains("billing") && claimB.label.contains("does not exist"), claimB.label)
        if let folder = ProcessInfo.processInfo.environment["CONFLICT_SHOTS"] {
            try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/live-card.png"))
        }
        let ask = app.buttons["conflictAsk-a"]
        XCTAssertEqual(ask.label, "Ask lantern")
        ask.tap()
        let asked = NSPredicate(format: "label == %@", "Asked lantern")
        expectation(for: asked, evaluatedWith: ask)
        waitForExpectations(timeout: 15)
        app.buttons["conflictDismiss"].tap()
        XCTAssertTrue(card.waitForNonExistence(timeout: 15), "Dismiss removes the card")
        app.buttons["hangUp"].tap()
        XCTAssertTrue(connect.waitForExistence(timeout: 15))
    }
}
