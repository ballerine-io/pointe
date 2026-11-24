import XCTest

/// The Home Screen widget, added through the Home Screen's own editor, for a screenshot of it as people see it. The
/// editor's buttons are the system's and change with iOS: run by hand (`-only-testing:PointeUITests/TalkWidgetUITests`
/// with POINTE_SHOTS set); it skips otherwise.
@MainActor
final class TalkWidgetUITests: XCTestCase {
    private let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")

    func testTheWidgetOnTheHomeScreen() throws {
        guard let dir = ProcessInfo.processInfo.environment["POINTE_SHOTS"], !dir.isEmpty else {
            throw XCTSkip("a screenshot run: set POINTE_SHOTS")
        }
        XCUIDevice.shared.press(.home)
        springboard.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.62)).press(forDuration: 1.5)
        let edit = springboard.buttons["Edit"]
        if edit.waitForExistence(timeout: 5) { edit.tap() }
        let add = springboard.buttons.matching(NSPredicate(format: "label CONTAINS[c] 'Widget'")).firstMatch
        XCTAssertTrue(add.waitForExistence(timeout: 5), springboard.debugDescription)
        add.tap()
        let search = springboard.searchFields.firstMatch
        XCTAssertTrue(search.waitForExistence(timeout: 5), springboard.debugDescription)
        search.tap()
        search.typeText("Pointe")
        let pointe = springboard.cells.matching(NSPredicate(format: "label CONTAINS 'Pointe'")).firstMatch
        let anyPointe = pointe.exists ? pointe : springboard.buttons.matching(NSPredicate(format: "label CONTAINS 'Pointe'")).firstMatch
        XCTAssertTrue(anyPointe.waitForExistence(timeout: 5), springboard.debugDescription)
        anyPointe.tap()
        let addWidget = springboard.buttons.matching(NSPredicate(format: "label ENDSWITH %@", "Add Widget")).firstMatch
        XCTAssertTrue(addWidget.waitForExistence(timeout: 5), springboard.debugDescription)
        addWidget.tap()
        let done = springboard.buttons["Done"]
        if done.waitForExistence(timeout: 3) { done.tap() }
        Thread.sleep(forTimeInterval: 2)
        let shot = XCUIScreen.main.screenshot()
        try shot.pngRepresentation.write(to: URL(fileURLWithPath: dir).appendingPathComponent("widget-home.png"))
    }

    /// The control in Control Center, added through its own editor.
    func testTheControlInControlCenter() throws {
        guard let dir = ProcessInfo.processInfo.environment["POINTE_SHOTS"], !dir.isEmpty else {
            throw XCTSkip("a screenshot run: set POINTE_SHOTS")
        }
        XCUIDevice.shared.press(.home)
        let top = springboard.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.005))
        top.press(forDuration: 0.1, thenDragTo: springboard.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.6)))
        Thread.sleep(forTimeInterval: 1)
        springboard.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.85)).press(forDuration: 1.5)
        let add = springboard.buttons.matching(NSPredicate(format: "label CONTAINS[c] 'Add a Control'")).firstMatch
        XCTAssertTrue(add.waitForExistence(timeout: 5), springboard.debugDescription)
        add.tap()
        let search = springboard.searchFields.firstMatch
        XCTAssertTrue(search.waitForExistence(timeout: 5), springboard.debugDescription)
        search.tap()
        search.typeText("Talk to Pointe")
        let control = springboard.buttons.matching(NSPredicate(format: "label CONTAINS 'Talk to Pointe'")).firstMatch
        XCTAssertTrue(control.waitForExistence(timeout: 5), springboard.debugDescription)
        try XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: dir).appendingPathComponent("control-gallery.png"))
        control.tap()
        Thread.sleep(forTimeInterval: 2)
        try XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: dir).appendingPathComponent("control-center.png"))
    }
}
