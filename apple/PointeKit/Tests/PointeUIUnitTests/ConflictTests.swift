import XCTest
@testable import PointeUI

final class ConflictTests: XCTestCase {
    private func status(_ json: String) throws -> API.Status {
        try JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    func testAnOlderDaemonWithoutTheAlarmHidesIt() throws {
        XCTAssertNil(try status(#"{"connected": true, "sessions": []}"#).conflicts)
    }

    func testTheFullContractDecodes() throws {
        let s = try status(#"""
        {"connected": true, "sessions": [], "conflicts": [{"id": "ab12", "a": "lantern", "b": "billing",
          "agent_a": "Codex", "agent_b": "OpenCode", "claim_a": "it passed", "claim_b": "it failed",
          "at_a": 1700000000, "at_b": 1700000720, "at": 1700000721, "why": "both cannot hold", "severity": "normal",
          "questions": {"a": "where?", "b": "which database?"}, "branches": {"a": "dev", "b": "main"},
          "asked": ["b"], "state": "open"}]}
        """#)
        let c = try XCTUnwrap(s.conflicts?.first)
        XCTAssertEqual(c.name("a"), "lantern")
        XCTAssertEqual(c.name("b"), "billing")
        XCTAssertEqual(c.agent_b, "OpenCode")
        XCTAssertEqual(c.branches, API.Branches(a: "dev", b: "main"))
        XCTAssertFalse(c.wasAsked("a"))
        XCTAssertTrue(c.wasAsked("b"))
        XCTAssertEqual(ConflictCopy.branches(c.branches!), "On different branches: dev and main")
    }

    func testOptionalFieldsMayBeMissing() throws {
        let c = try XCTUnwrap(try status(#"""
        {"connected": true, "sessions": [], "conflicts": [{"id": "x", "a": "a1", "b": "b1", "claim_a": "p", "claim_b": "q"}]}
        """#).conflicts?.first)
        XCTAssertNil(c.branches)
        XCTAssertFalse(c.wasAsked("a"))
        XCTAssertEqual(ConflictCopy.time(nil), "")
    }

    func testCopyMatchesThePage() {
        XCTAssertEqual(ConflictCopy.ask("lantern"), "Ask lantern")
        XCTAssertEqual(ConflictCopy.asked("lantern"), "Asked lantern")
        XCTAssertEqual(ConflictCopy.more(1), "1 more disagreement")
        XCTAssertEqual(ConflictCopy.more(3), "3 more disagreements")
        XCTAssertEqual(ConflictCopy.refusal("no call is up"), "Connect to ask.")
        XCTAssertEqual(ConflictCopy.refusal("nothing goes to a session during a meeting"), ConflictCopy.inMeeting)
        XCTAssertEqual(ConflictCopy.refusal("no such conflict"), "That conflict is gone.")
        XCTAssertEqual(ConflictCopy.refusal(""), "Not done.")
    }

    func testPrefsDefaultToOnAndSpoken() throws {
        let old = try JSONDecoder().decode(API.Prefs.self, from: Data("{}".utf8))
        XCTAssertTrue(old.conflictsOn)
        XCTAssertTrue(old.conflictsSpoken)
        let set = try JSONDecoder().decode(API.Prefs.self, from: Data(#"{"conflicts.on": false, "conflicts.spoken": false}"#.utf8))
        XCTAssertFalse(set.conflictsOn)
        XCTAssertFalse(set.conflictsSpoken)
    }
}
