import XCTest

/// Driven by apps/ios/e2e/bad_network.py: a test daemon with a stand-in voice, reached through a shaped network (latency,
/// loss, a cap, an outage, a network switch). The app's microphone is a synthetic tone (POINTE_SYNTHETIC_MIC): no
/// microphone is opened. The app types its own lines on cue (POINTE_TYPE_AT) and keeps its own trace: this test only
/// connects, then leaves the screen alone while the driver measures, since every query reads the whole screen on the
/// app's main thread. At the end it prints what the app saw; the driver judges, with the daemon's log beside it.
final class BadNetworkUITests: XCTestCase {
    func testTheCallRidesABadNetwork() throws {
        let env = ProcessInfo.processInfo.environment
        guard let link = env["POINTE_PAIR"], let hold = Double(env["POINTE_HOLD_SECS"] ?? "") else {
            throw XCTSkip("needs the shaped test daemon: run apps/ios/e2e/bad_network.py")
        }
        let app = XCUIApplication()
        app.launchEnvironment["POINTE_PAIR"] = link
        app.launchEnvironment["POINTE_SYNTHETIC_MIC"] = "1"
        app.launchEnvironment["POINTE_TYPE_AT"] = env["POINTE_LINES"] ?? ""
        app.launch()
        let connect = app.buttons["Connect"]
        XCTAssertTrue(connect.waitForExistence(timeout: 30), "the app paired and shows Connect")
        connect.tap()
        XCTAssertTrue(app.buttons["hangUp"].waitForExistence(timeout: 30), "the call is up")
        print("NETCALL up \(Date().timeIntervalSince1970)")
        Thread.sleep(forTimeInterval: hold)
        let trace = app.otherElements["netTrace"].firstMatch
        print("NETTRACE \(trace.exists ? (trace.value as? String ?? "") : "none")")
        let busy = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "A call is already up")).firstMatch.exists
        print("NETEND up=\(app.buttons["hangUp"].exists) busy=\(busy)")
    }
}
