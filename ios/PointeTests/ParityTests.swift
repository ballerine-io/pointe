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

final class LocalModeTests: XCTestCase {
    func testTheLocalModeLineIsDecodedAndAnOlderMacSendsNone() throws {
        let s = try JSONDecoder().decode(API.Status.self, from: Data(
            #"{"connected": true, "sessions": [], "local": {"mode": "full", "models": "missing", "line": "Fully local: on · models not downloaded (pointe local)"}}"#.utf8))
        XCTAssertEqual(s.local?.line, "Fully local: on · models not downloaded (pointe local)")
        XCTAssertEqual(s.local?.models, "missing")
        XCTAssertEqual(s.local?.short, "Fully local · models missing")  // what fits a menu item
        XCTAssertNil(try JSONDecoder().decode(API.Status.self, from: Data(#"{"connected": true, "sessions": []}"#.utf8)).local)
    }
}

final class CallElsewhereTests: XCTestCase {
    func testWithNoCallHereTheMacsCallShowsAsElsewhere() {
        XCTAssertEqual(CallView.offTitle(reachable: true, macOnACall: true), "On a call elsewhere")
        XCTAssertEqual(CallView.offTitle(reachable: true, macOnACall: false), "Not connected")
        XCTAssertEqual(CallView.offTitle(reachable: false, macOnACall: true), "Mac not reachable")  // a stale status says nothing
    }
}

final class DriveRefusedTests: XCTestCase {
    func testTheMacsReasonOrThePagesLine() {
        XCTAssertEqual(DriveCopy.refused("a meeting is on"), "A meeting is on.")
        XCTAssertEqual(DriveCopy.refused("no call is up"), "Start the call first.")
        XCTAssertEqual(DriveCopy.refused("HTTP 500"), "Drive mode did not change.")  // no reason given
        XCTAssertEqual(DriveCopy.refused(""), "Drive mode did not change.")
    }
}

final class BriefingScheduleTests: XCTestCase {
    func testTheSchedulesChecksAreThePages() {
        XCTAssertEqual(BriefingCopy.check(time: "08:30", days: []), "Pick at least one day for the briefing.")
        XCTAssertNil(BriefingCopy.check(time: "08:30", days: [0]))
        XCTAssertNil(BriefingCopy.check(time: "", days: []))  // not scheduled: no day needed
    }

    func testNotSavedSaysTheMacsReason() {
        XCTAssertEqual(BriefingCopy.notSaved("not a setting, or a wrong value: briefing.days"),
                       "Not saved: not a setting, or a wrong value: briefing.days.")
        XCTAssertEqual(BriefingCopy.notSaved("HTTP 502"), "Not saved: the Mac did not answer.")
        XCTAssertEqual(BriefingCopy.notSaved(nil), "Not saved: the Mac did not answer.")
    }
}

final class RecentRequestsTests: XCTestCase {
    func testRecentRequestsAndTheContextCountAreDecodedAndWritten() throws {
        let s = try JSONDecoder().decode(API.Status.self, from: Data(#"""
            {"connected": true, "sessions": [], "tokens": {"context": 12480, "reply": 40, "audio_in": 0, "at": "10:42:07"},
             "recent": [{"at": "10:41:50", "said": "tell docs", "message": "x", "to": ["docs", "billing/main"], "how": "(named)"},
                        {"at": "10:42:01", "said": "push it", "message": "y", "to": [], "how": "blocked: ambiguous"}]}
            """#.utf8))
        XCTAssertEqual(SessionsCopy.routed(s.recent![0]), "10:41:50 → docs + billing/main (named)")
        XCTAssertEqual(SessionsCopy.routed(s.recent![1]), "10:42:01 blocked: ambiguous")
        XCTAssertEqual(SessionsCopy.context(s.tokens), "12,480 tokens as of 10:42:07")
        XCTAssertNil(SessionsCopy.context(nil))  // no call yet: nothing to count
    }
}

final class RenameTests: XCTestCase {
    func testARefusedRenameSaysTheMacsReason() {
        XCTAssertEqual(SessionsCopy.renameRefused("pricing is already taken"), "Not renamed: pricing is already taken.")
        XCTAssertEqual(SessionsCopy.renameRefused("HTTP 500"), "Not renamed: the Mac did not answer.")
    }
}
