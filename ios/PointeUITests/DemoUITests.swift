import XCTest

/// "Try a demo" on the pairing screen: what App Review sees without a Mac. No launch arguments, as in a Release build.
@MainActor
final class DemoUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    func testTryADemoFromThePairingScreenAndLeaveIt() {
        let app = XCUIApplication()
        app.launchEnvironment["POINTE_FORGET"] = "1"
        app.launch()

        let tryDemo = app.buttons["tryDemo"]
        XCTAssertTrue(tryDemo.waitForExistence(timeout: 15), "the pairing screen offers the demo")
        tryDemo.tap()

        let badge = app.buttons["demoBadge"]
        XCTAssertTrue(badge.waitForExistence(timeout: 10), "the demo says it is one")
        XCTAssertEqual(badge.label, "Exit demo")
        let deny = app.buttons["Deny"]
        XCTAssertTrue(deny.waitForExistence(timeout: 5), "a sample request waits for an answer")
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "git push --force-with-lease")).firstMatch.exists,
                      "the exact command is on screen")
        deny.tap()
        XCTAssertTrue(deny.waitForNonExistence(timeout: 5), "the answer clears the card, as a Mac would")

        badge.tap()
        XCTAssertTrue(tryDemo.waitForExistence(timeout: 10), "out of the demo, back to pairing")
        XCTAssertFalse(app.buttons["demoBadge"].exists)
    }

    /// What App Review taps in the demo answers as a Mac would: a chip focuses, All goes back, a typed line shows, clean
    /// up toggles, and a swipe in the Sessions sheet takes a session off. A control that does nothing reads as broken.
    func testTheDemoPlaysAlongWithTheSessionsTypingAndSettings() {
        let app = XCUIApplication()
        app.launchEnvironment["POINTE_FORGET"] = "1"
        app.launch()
        XCTAssertTrue(app.buttons["tryDemo"].waitForExistence(timeout: 15))
        app.buttons["tryDemo"].tap()
        let line = app.descendants(matching: .any)["statusLine"].firstMatch
        XCTAssertTrue(line.waitForExistence(timeout: 10))

        let docs = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "docs,")).firstMatch
        XCTAssertTrue(docs.waitForExistence(timeout: 5))
        docs.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()  // on screen; the strip's scroll view fails XCUITest's hittable check
        XCTAssertTrue(NSPredicate(format: "label CONTAINS %@", "Focused on docs").wait(for: line, timeout: 5), "a chip focuses: \(line.label)")
        app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "All sessions")).firstMatch
            .coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        XCTAssertTrue(NSPredicate(format: "NOT (label CONTAINS %@)", "Focused on").wait(for: line, timeout: 5), "All goes back: \(line.label)")
        XCTAssertTrue(app.buttons["All sessions, orchestrator mode, on"].exists)

        app.buttons["Type"].tap()
        let field = app.descendants(matching: .any)["typeField"].firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.tap()
        field.typeText("ship the change log too\n")
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "ship the change log too")).firstMatch
            .waitForExistence(timeout: 5), "the typed line shows in the conversation")
        app.buttons["Type"].tap()

        // A Toggle in a menu reads as a switch or as a button with a check, by iOS release.
        func cleanup() -> XCUIElement {
            app.descendants(matching: .any).matching(NSPredicate(format: "label == %@ AND (elementType == %d OR elementType == %d)",
                "Clean up my words", XCUIElement.ElementType.switch.rawValue, XCUIElement.ElementType.button.rawValue)).firstMatch
        }
        func isOn(_ e: XCUIElement) -> Bool { (e.value as? String) == "1" || e.isSelected }
        sleep(1)  // the keyboard goes
        app.buttons["Settings"].tap()
        XCTAssertTrue(cleanup().waitForExistence(timeout: 5), "Settings has Clean up my words")
        XCTAssertFalse(isOn(cleanup()))
        cleanup().tap()
        sleep(1)
        app.buttons["Settings"].tap()
        XCTAssertTrue(cleanup().waitForExistence(timeout: 5))
        XCTAssertTrue(isOn(cleanup()), "clean up stays on: \(cleanup().debugDescription)")
        app.coordinate(withNormalizedOffset: CGVector(dx: 0.3, dy: 0.21)).tap()
        sleep(1)

        app.buttons["Sessions"].tap()
        let row = app.cells.containing(.staticText, identifier: "docs").firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 10))
        row.swipeLeft()
        app.buttons["Disconnect"].firstMatch.tap()
        let confirm = app.buttons["confirmDisconnect"].firstMatch
        XCTAssertTrue(confirm.waitForExistence(timeout: 5))
        confirm.tap()
        XCTAssertTrue(row.waitForNonExistence(timeout: 5), "docs is off the voice")
    }

    func testTheLaunchArgumentDemoShowsNoBadge() {
        let app = XCUIApplication()
        app.launchArguments = ["-demo", "request"]
        app.launch()
        XCTAssertTrue(app.buttons["Approve"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.buttons["demoBadge"].exists, "screenshots and tests keep the plain header")
    }
}
