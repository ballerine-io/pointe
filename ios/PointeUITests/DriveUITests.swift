import XCTest

/// Drive mode on the -demo fixture: no Mac needed. Screenshots go to DRIVE_SHOTS when it names a folder.
@MainActor
final class DriveUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen]
        app.launch()
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["DRIVE_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    private func any(_ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    /// At the accessibility sizes the drive screen's words scroll in its own box: the header stays under the status bar,
    /// and I've stopped and the bar stay on the screen. A stack that did not fit pushed them off both edges.
    func testAtTheLargestTypeDriveModeKeepsTheHeaderAndTheBarOnTheScreen() {
        for screen in ["drive", "machinesDrive"] {
            app = XCUIApplication()
            app.launchArguments = ["-demo", screen, "-demoEnglish", "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXL"]
            app.launch()
            XCTAssertTrue(any("driveLine").waitForExistence(timeout: 15), screen)
            let window = app.windows.firstMatch.frame
            for name in ["Settings", "driveButton", "driveStop", "micRing", "hangUp"] {
                let element = app.buttons[name]
                XCTAssertTrue(element.exists, "\(screen): \(name)")
                XCTAssertGreaterThanOrEqual(element.frame.minY, 44, "\(screen): \(name) is under the status bar")
                XCTAssertLessThanOrEqual(element.frame.maxY, window.maxY + 0.5, "\(screen): \(name) is on the screen")
                XCTAssertTrue(element.isHittable, "\(screen): \(name) can be tapped")
            }
            shot("drive-ax-\(screen)")
            app.terminate()
        }
    }

    func testWhileDrivingNothingAsksForATapUntilIveStopped() {
        launch("drive")
        XCTAssertTrue(any("driveLine").waitForExistence(timeout: 15))
        XCTAssertEqual(any("driveLine").label, "billing/main needs you")
        XCTAssertTrue(any("driveRequest").label.contains("Not for the road: it waits until you stop. Say no to deny it."),
                      any("driveRequest").label)
        XCTAssertFalse(app.buttons["Approve"].exists, "no Approve while driving")
        XCTAssertFalse(app.buttons["Deny"].exists, "no Deny while driving")
        XCTAssertFalse(app.buttons["Type"].exists, "typing folds away")
        XCTAssertEqual(app.buttons["driveButton"].value as? String, "On")
        shot("drive-on")

        app.buttons["driveStop"].tap()
        XCTAssertTrue(any("driveLine").waitForNonExistence(timeout: 5))
        XCTAssertTrue(app.buttons["Approve"].waitForExistence(timeout: 5), "stopped: the normal card answers it")
        XCTAssertTrue(app.buttons["Type"].exists)
        XCTAssertEqual(app.buttons["driveButton"].value as? String, "Off")
        shot("drive-stopped")

        app.buttons["driveButton"].tap()
        XCTAssertTrue(any("driveLine").waitForExistence(timeout: 5), "the Drive button turns it back on")
        XCTAssertFalse(app.buttons["Approve"].exists)
    }

    func testAMacWithoutDriveModeShowsNoDriveButton() {
        launch("request")
        XCTAssertTrue(app.buttons["Approve"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.buttons["driveButton"].exists)
    }
}
