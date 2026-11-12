import XCTest
@testable import Pointe

/// Challenge me: the daemon's contract decodes (and an older daemon without it still does), the copy is the page's,
/// and a closed challenge stays closed until a new one starts.
final class ChallengeTests: XCTestCase {
    private func status(_ json: String) throws -> API.Status {
        try JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    private let onJSON = #"""
    {"connected": true, "sessions": [], "mode": "orchestrator",
     "challenge": {"id": "c1", "on": true, "since": 1700000000, "ended_at": null,
                   "plan": "Move the retry loop into a queue.", "sessions": ["billing/main"], "objections": 1,
                   "verdict": null, "evidence": 4,
                   "items": [{"kind": "objection", "text": "A queue doubles charges on failover.", "at": 1700000010},
                             {"kind": "rebuttal", "text": "We dedupe by idempotency key.", "at": 1700000020}]}}
    """#

    func testAnOlderDaemonWithoutChallengeStillDecodes() throws {
        XCTAssertNil(try status(#"{"connected": true, "sessions": []}"#).challenge)
        XCTAssertNil(try status(#"{"connected": true, "sessions": [], "challenge": null}"#).challenge)
    }

    func testTheStatusContractDecodes() throws {
        let c = try XCTUnwrap(try status(onJSON).challenge)
        XCTAssertTrue(c.on)
        XCTAssertEqual(c.id, "c1")
        XCTAssertEqual(c.plan, "Move the retry loop into a queue.")
        XCTAssertEqual(c.sessions, ["billing/main"])
        XCTAssertEqual(c.items?.map(\.kind), ["objection", "rebuttal"])
        XCTAssertNil(c.verdict)
    }

    func testAnEndedChallengeDecodes() throws {
        let c = try XCTUnwrap(try status(#"""
        {"connected": true, "sessions": [],
         "challenge": {"id": "c1", "on": false, "since": 1700000000, "ended_at": 1700000100, "plan": "", "sessions": [],
                       "objections": 2, "verdict": "Ship it behind a flag.", "evidence": 0,
                       "items": [{"kind": "verdict", "text": "Ship it behind a flag.", "at": 1700000100}]}}
        """#).challenge)
        XCTAssertFalse(c.on)
        XCTAssertEqual(c.ended_at, 1700000100)
        XCTAssertEqual(c.verdict, "Ship it behind a flag.")
    }

    func testItemLabelsAreThePages() {
        XCTAssertEqual(ChallengeCopy.label("objection"), "Objection")
        XCTAssertEqual(ChallengeCopy.label("rebuttal"), "You")
        XCTAssertEqual(ChallengeCopy.label("verdict"), "Verdict")
    }

    func testTheCopyIsThePages() {
        XCTAssertEqual(ChallengeCopy.title(on: true), "Challenge")
        XCTAssertEqual(ChallengeCopy.title(on: false), "Challenge ended")
        XCTAssertEqual(ChallengeCopy.lede, "I argue against your plan, one objection at a time. Nothing is sent while it's on.")
        XCTAssertEqual(ChallengeCopy.planHeading, "The plan")
        XCTAssertEqual(ChallengeCopy.end, "End challenge")
        XCTAssertEqual(ChallengeCopy.hint, "Or say “you've made your point”, “verdict” or “back to normal”.")
        XCTAssertEqual(ChallengeCopy.close, "Close")
        XCTAssertEqual(ChallengeCopy.menuItem, "Challenge")
        XCTAssertEqual(ChallengeCopy.fromBrainstorm, "Challenge it")
        XCTAssertEqual(ChallengeCopy.state, "Challenging")
    }

    func testAnEmptyPlanAsksForOne() {
        XCTAssertEqual(ChallengeCopy.plan(""), "No plan yet: say it in a sentence or two.")
        XCTAssertEqual(ChallengeCopy.plan("  \n"), "No plan yet: say it in a sentence or two.")
        XCTAssertEqual(ChallengeCopy.plan(nil), "No plan yet: say it in a sentence or two.")
        XCTAssertEqual(ChallengeCopy.plan("Use a queue."), "Use a queue.")
    }

    func testAClosedChallengeStaysClosedUntilANewOne() throws {
        let on = try XCTUnwrap(try status(onJSON).challenge)
        XCTAssertTrue(ChallengeCopy.shown(on, dismissed: nil))
        XCTAssertTrue(ChallengeCopy.shown(on, dismissed: "c1"), "while on it cannot be closed")
        var ended = on
        ended.on = false
        XCTAssertTrue(ChallengeCopy.shown(ended, dismissed: nil), "ended: shown until closed")
        XCTAssertFalse(ChallengeCopy.shown(ended, dismissed: "c1"), "closed here")
        var next = ended
        next.id = "c2"
        XCTAssertTrue(ChallengeCopy.shown(next, dismissed: "c1"), "a new challenge shows again")
        XCTAssertFalse(ChallengeCopy.shown(nil, dismissed: nil))
    }

    func testRightToLeftTextIsDetected() {
        XCTAssertTrue(ChallengeCopy.rightToLeft("תור יכפיל חיובים"))
        XCTAssertTrue(ChallengeCopy.rightToLeft("  42 תור"), "the first strong letter decides")
        XCTAssertFalse(ChallengeCopy.rightToLeft("A queue, then תור"))
        XCTAssertFalse(ChallengeCopy.rightToLeft(""))
    }
}
