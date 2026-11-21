import XCTest

/// Push to talk on a real call, for ios/e2e/ptt_latency.py: connect, hold the ring a few times, and print the app's trace
/// of each press (the touch to the open gate, the touch to the first chunk sent, and from when that audio was captured).
/// Runs only when the driver passes a pairing link.
@MainActor
final class PushToTalkLatencyUITests: XCTestCase {
    func testPressToFirstFrame() throws {
        guard let link = ProcessInfo.processInfo.environment["POINTE_PAIR"] else { throw XCTSkip("run by ios/e2e/ptt_latency.py") }
        let app = XCUIApplication()
        app.launchArguments = ["-talkStyle", "hold"]
        app.launchEnvironment["POINTE_PAIR"] = link
        app.launch()
        let connect = app.buttons["Connect"].firstMatch
        XCTAssertTrue(connect.waitForExistence(timeout: 30), "paired, shows Connect")
        connect.tap()
        XCTAssertTrue(app.buttons["hangUp"].waitForExistence(timeout: 30), "the call is up")
        let ring = app.buttons["micRing"].firstMatch
        XCTAssertTrue(NSPredicate(format: "label == %@", "Hold to talk").wait(for: ring, timeout: 15), "push to talk, from the Mac")
        sleep(2)  // the microphone has been running a while, as on any call
        for i in 1...6 {
            ring.press(forDuration: 1.2)
            RunLoop.current.run(until: Date().addingTimeInterval(0.6))
            let trace = (ring.value as? String) ?? ""
            let held = trace.split(separator: " ").dropFirst().first.map(String.init) ?? "0"
            print("PTTTRACE \(i) held_ms=\(held) \(trace)")
            RunLoop.current.run(until: Date().addingTimeInterval(0.9))
        }
        app.buttons["hangUp"].tap()
    }
}
