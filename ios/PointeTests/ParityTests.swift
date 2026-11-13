import XCTest
@testable import Pointe

/// What the page already did and the app now does too.
final class ParityTests: XCTestCase {
    private func status(_ json: String) throws -> API.Status {
        try JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    func testTheMacsProblemIsDecodedAndShownAfterTheAppsOwn() throws {
        let s = try status(#"{"connected": true, "sessions": [], "problem": "the brain key was refused"}"#)
        XCTAssertEqual(s.problem, "the brain key was refused")
        XCTAssertNil(try status(#"{"connected": true, "sessions": []}"#).problem)  // an older Mac sends none
        XCTAssertEqual(CallView.shownProblem(screen: nil, call: nil, mac: s.problem), "the brain key was refused")  // as the page shows it
        XCTAssertEqual(CallView.shownProblem(screen: "Start the call first.", call: nil, mac: s.problem), "Start the call first.")
        XCTAssertEqual(CallView.shownProblem(screen: nil, call: "Pointe needs the microphone.", mac: s.problem), "Pointe needs the microphone.")
        XCTAssertNil(CallView.shownProblem(screen: nil, call: nil, mac: ""))
    }
}

final class IdleHangupTests: XCTestCase {
    func testAnIdleHangUpIsNotRedialledButADroppedLinkIs() throws {
        let idle = try JSONDecoder().decode(API.Status.self, from: Data(#"{"connected": false, "sessions": [], "idle_hangup": true}"#.utf8))
        XCTAssertEqual(idle.idle_hangup, true)
        XCTAssertFalse(Call.redials(idleHangup: idle.idle_hangup))
        XCTAssertTrue(Call.redials(idleHangup: false))
        XCTAssertTrue(Call.redials(idleHangup: nil))  // the Mac unreachable, or one without the field: keep trying
        XCTAssertFalse(Call.idleHangupNote.isEmpty)
    }
}
