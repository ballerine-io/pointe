import XCTest

/// The Mac app holding machines besides this Mac (docs/design/multi-machine-clients.md, 1.8): the menu over the call
/// screen lists this Mac first, then each machine with how it is reached, and choosing one moves the call there. The
/// stand-in machines are names under `.invalid`, which never resolve.
final class MacMachinesUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }
    override func tearDown() { app?.terminate() }

    private func line(_ host: String, _ fp: Character, via: String) -> String {
        "pointe://pair?v=1&host=\(host)&port=7443&fp=\(String(repeating: fp, count: 64))&key=\(String(repeating: "k", count: 40))&via=\(via)"
    }

    @MainActor private func launch(several: Bool) -> XCUIElement {
        app = XCUIApplication()
        app.launchArguments = ["-demo", "call", "-PointeOpenWindow", "YES", "-ApplePersistenceIgnoreState", "YES"]
        app.launchEnvironment["POINTE_MEMORY_VAULT"] = "1"
        app.launchEnvironment["POINTE_PAIR_MORE"] = line("kite.invalid", "b", via: "host") + " " + line("ledger.invalid", "c", via: "tailscale")
        if several { app.launchEnvironment["POINTE_MACHINES"] = "1" }
        app.launch()
        app.activate()
        let window = app.windows["pointe.main"]
        XCTAssertTrue(window.waitForExistence(timeout: 10), "the call window opens")
        return window
    }

    /// The menu's own label says the machine the call goes to (MacMachineMenu sets it from the session): the test waits
    /// for that state, and opens the menu again if a click on an item did not land (the menu closed under it).
    @MainActor func testTheMenuListsThisMacThenEachMachineAndChoosingOneMovesTheCall() {
        let window = launch(several: true)
        let menu = window.descendants(matching: .any)["machineMenu"].firstMatch
        XCTAssertTrue(menu.waitForExistence(timeout: 10))
        XCTAssertTrue(menu.label.contains("This Mac"), menu.label)
        for attempt in 0..<2 where !menu.label.contains("kite.invalid") {
            menu.click()
            let kite = app.menuItems["kite.invalid · Twingate or VPN"]
            XCTAssertTrue(kite.waitForExistence(timeout: 10), "each machine says how this Mac reaches it (attempt \(attempt))")
            XCTAssertTrue(app.menuItems["This Mac"].exists)
            XCTAssertTrue(app.menuItems["ledger.invalid · Tailscale"].exists)
            kite.click()
            _ = XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate(format: "label CONTAINS %@", "kite.invalid"), object: menu)],
                               timeout: 30)
        }
        XCTAssertTrue(menu.label.contains("kite.invalid"), "the call moved: \(menu.label)")
    }

    @MainActor func testWithTheFlagOffThereIsNoMenu() {
        let window = launch(several: false)
        sleep(3)
        XCTAssertFalse(window.descendants(matching: .any)["machineMenu"].exists, "several machines is a Labs setting, off by default")
    }
}
