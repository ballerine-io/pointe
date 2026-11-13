import XCTest

/// What the page did and the app now does too, on the -demo fixtures. No Mac needed.
/// Screenshots go to PARITY_SHOTS when it names a folder.
@MainActor
final class ParityUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen]
        app.launch()
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["PARITY_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    private func any(_ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    func testSettingsShowTheMacsLocalModeReadOnly() throws {
        launch("call")
        XCTAssertTrue(app.buttons["Settings"].waitForExistence(timeout: 15))
        app.buttons["Settings"].tap()
        let line = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label CONTAINS %@", "Voice stays on your Mac · models here")).firstMatch
        if !line.waitForExistence(timeout: 3) { app.swipeUp() }  // a long menu scrolls
        shot("settings-local")
        XCTAssertTrue(line.waitForExistence(timeout: 5), "the local mode line is in Settings")
    }
}
