import XCTest

/// A phone that holds several machines (docs/design/multi-machine-clients.md): the list with how each is reached and
/// whether it answers, a tap that moves calls to another, Remove, and the flag that keeps it all off by default. The
/// stand-in machines are names under `.invalid`, which never resolve, as a Twingate name does not while its connector
/// is stopped: both show "Not reachable" with the cause.
@MainActor
final class MachinesUITests: XCTestCase {
    private let key = String(repeating: "k", count: 40)
    private func line(_ host: String, _ fp: Character, via: String) -> String {
        "pointe://pair?v=1&host=\(host)&port=7443&fp=\(String(repeating: fp, count: 64))&key=\(key)&via=\(via)"
    }

    override func setUp() { continueAfterFailure = false }

    private func launch(several: Bool) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["POINTE_FORGET"] = "1"
        app.launchEnvironment["POINTE_MEMORY_VAULT"] = "1"  // unsigned in CI: the Simulator's Keychain keeps nothing
        app.launchEnvironment["POINTE_PAIR"] = line("studio.invalid", "a", via: "tailscale")
        app.launchEnvironment["POINTE_PAIR_MORE"] = line("kite.invalid", "b", via: "host")
        if several { app.launchEnvironment["POINTE_MACHINES"] = "1" }
        app.launch()
        return app
    }

    private func any(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    private func shot(_ app: XCUIApplication, _ name: String) {
        let s = XCTAttachment(screenshot: app.screenshot())
        s.name = name
        s.lifetime = .keepAlways
        add(s)
    }

    func testTheListShowsEachMachineItsRouteAndThatItIsNotReachable() {
        let app = launch(several: true)
        let bar = any(app, "machineBar")
        XCTAssertTrue(bar.waitForExistence(timeout: 20), "the machine the call goes to, over the call")
        XCTAssertTrue(bar.label.contains("studio.invalid"), bar.label)
        bar.tap()
        XCTAssertTrue(any(app, "machineRow-studio.invalid").waitForExistence(timeout: 10))
        XCTAssertTrue(any(app, "machineRow-kite.invalid").exists, "both machines are on the phone")
        let kite = any(app, "machineState-kite.invalid")
        let down = NSPredicate(format: "label CONTAINS %@", "Not reachable")
        expectation(for: down, evaluatedWith: kite)
        waitForExpectations(timeout: 30)
        XCTAssertTrue(kite.label.contains("Twingate or VPN"), "how the phone reaches it: \(kite.label)")
        XCTAssertTrue(any(app, "machineState-studio.invalid").label.contains("Tailscale"))
        shot(app, "machines-list")
    }

    func testATapMovesCallsToAnotherMachineAndRemoveTakesOneOff() {
        let app = launch(several: true)
        let bar = any(app, "machineBar")
        XCTAssertTrue(bar.waitForExistence(timeout: 20))
        bar.tap()
        let kite = any(app, "machineRow-kite.invalid")
        XCTAssertTrue(kite.waitForExistence(timeout: 10))
        kite.tap()
        let moved = NSPredicate(format: "label CONTAINS %@", "kite.invalid")
        expectation(for: moved, evaluatedWith: any(app, "machineBar"))
        waitForExpectations(timeout: 15)
        shot(app, "machines-switched")

        any(app, "machineBar").tap()
        let studio = any(app, "machineRow-studio.invalid")
        XCTAssertTrue(studio.waitForExistence(timeout: 10))
        studio.swipeLeft()
        app.buttons["Remove"].firstMatch.tap()
        let confirm = app.buttons.matching(NSPredicate(format: "label == %@", "Remove")).element(boundBy: 0)
        XCTAssertTrue(confirm.waitForExistence(timeout: 5))
        confirm.tap()
        let gone = NSPredicate(format: "exists == false")
        expectation(for: gone, evaluatedWith: any(app, "machineRow-studio.invalid"))
        waitForExpectations(timeout: 10)
        XCTAssertTrue(any(app, "machineRow-kite.invalid").exists, "the other machine stays")
    }

    func testWithTheFlagOffThereIsNoListAndOneMachine() {
        let app = launch(several: false)
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 15))
        sleep(3)
        XCTAssertFalse(any(app, "machineBar").exists, "several machines is a Labs setting, off by default")
    }
}
