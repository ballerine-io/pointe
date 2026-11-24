import XCTest

/// Settings, the sheet behind the ••• button: a list longer than a screen, so an item may need scrolling to.
extension XCUIApplication {
    var settingsOpen: Bool { navigationBars["Settings"].exists }

    func openSettings() {
        guard !settingsOpen else { return }
        let button = buttons["Settings"].firstMatch
        XCTAssertTrue(button.waitForExistence(timeout: 15), "the ••• button")
        button.tap()
        XCTAssertTrue(navigationBars["Settings"].waitForExistence(timeout: 5), "Settings opens")
    }

    /// An item of Settings by its identifier or its words, opened and scrolled to.
    func settingsItem(_ id: String, _ type: XCUIElement.ElementType = .any) -> XCUIElement {
        openSettings()
        let item = descendants(matching: type)[id].firstMatch
        let list = collectionViews.firstMatch
        let bottom = windows.firstMatch.frame.maxY - 60  // clear of the screen's edge, where a tap can miss
        func shown() -> Bool { item.exists && item.isHittable && item.frame.maxY < bottom }
        var swiped = false
        for _ in 0..<6 where !shown() { list.swipeUp(velocity: .slow); swiped = true }  // the last row stays near the edge
        for _ in 0..<6 where !(item.exists && item.isHittable) { list.swipeDown(velocity: .slow); swiped = true }
        if swiped { sleep(1) }  // a tap while the list still glides stops it instead of reaching the item
        return item
    }

    /// A switch in Settings: the tap goes to the switch itself, not to the words beside it.
    func flipSetting(_ id: String) {
        let row = settingsItem(id, .switch)
        XCTAssertTrue(row.exists, "Settings has \(id)")
        let control = row.switches.firstMatch
        (control.exists ? control : row).tap()
    }

    func closeSettings() {
        guard settingsOpen else { return }
        navigationBars["Settings"].buttons["Done"].tap()
        XCTAssertTrue(navigationBars["Settings"].waitForNonExistence(timeout: 5), "Settings closes")
    }
}
