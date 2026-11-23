import XCTest

/// Driven by tests/e2e/ios_phone_pair.py: a test daemon, a code made by the page's route, and the link passed in
/// TEST_RUNNER_POINTE_PAIR_CODE_LINK. Opened by the system, as the Camera app's "Open in Pointe" does, the link pairs
/// nothing and says to scan inside Pointe; pasted in the app, it pairs once the owner confirms the Mac it names.
final class PairByLinkUITests: XCTestCase {
    func testALinkFromOutsidePairsNothingAndTheSameCodeInTheAppPairsAfterAConfirm() throws {
        guard let link = ProcessInfo.processInfo.environment["POINTE_PAIR_CODE_LINK"], let url = URL(string: link),
              let host = URLComponents(string: link)?.queryItems?.first(where: { $0.name == "host" })?.value else {
            throw XCTSkip("needs a test daemon: run tests/e2e/ios_phone_pair.py, which sets TEST_RUNNER_POINTE_PAIR_CODE_LINK")
        }
        let mac = ProcessInfo.processInfo.environment["POINTE_PAIR_MAC"] ?? "your Mac"
        let app = XCUIApplication()
        app.launchEnvironment["POINTE_FORGET"] = "1"
        app.launch()
        XCTAssertTrue(app.buttons["Pair"].waitForExistence(timeout: 15), "unpaired: the pairing screen shows")
        attach(app, "1-unpaired")

        open(url)
        XCTAssertTrue(app.staticTexts["scanInside"].waitForExistence(timeout: 20), "the opened link says to scan inside Pointe")
        XCTAssertFalse(app.buttons["Connect"].exists, "and pairs nothing")
        attach(app, "2-opened-from-outside")
        app.buttons["scanInsideScan"].tap()

        let field = app.textFields["or paste the pointe:// link"]
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        field.tap()
        field.typeText(link)
        app.buttons["Pair"].tap()
        let confirm = app.alerts.buttons["confirmPairing"]
        XCTAssertTrue(confirm.waitForExistence(timeout: 10), "the app asks before it pairs")
        XCTAssertTrue(app.alerts.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", host)).firstMatch.exists,
                      "and names the Mac")
        attach(app, "3-confirm")
        confirm.tap()
        let note = app.staticTexts["pairing-note"]
        XCTAssertTrue(note.waitForExistence(timeout: 20), "the app says what became of the code")
        XCTAssertTrue(says(note, "Paired with \(mac). Tap Connect to call.", within: 20), "it says it paired: \(note.label)")
        XCTAssertTrue(app.buttons["Connect"].waitForExistence(timeout: 10), "paired: the call screen shows Connect")
        attach(app, "4-paired")

        open(url)  // while paired: the link changes nothing
        XCTAssertTrue(app.staticTexts["scanInside"].waitForExistence(timeout: 20))
        app.buttons["Not now"].tap()
        XCTAssertTrue(app.buttons["Connect"].waitForExistence(timeout: 10), "the pairing it has stays")
        attach(app, "5-opened-again")
    }

    private func says(_ element: XCUIElement, _ text: String, within seconds: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(seconds)
        while Date() < deadline {
            if element.exists && element.label.contains(text) { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.3))
        }
        return false
    }

    /// As the Camera app: the system opens the link, and may ask first whether to open it in Pointe.
    private func open(_ url: URL) {
        XCUIDevice.shared.system.open(url)
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let confirm = springboard.buttons["Open"]
        if confirm.waitForExistence(timeout: 3) { confirm.tap() }
    }

    private func attach(_ app: XCUIApplication, _ name: String) {
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = name
        shot.lifetime = .keepAlways
        add(shot)
    }
}
