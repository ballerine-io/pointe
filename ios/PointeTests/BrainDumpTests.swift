import XCTest
@testable import Pointe

/// Brain dump (BrainDump.swift): the status decodes, an older Mac sends none, the button's word follows the state, the
/// send's target is picked the same way as on the page, and the copy is the page's word for word (tests/test_brain_dump.py
/// checks the three copies agree; here, the app's own invariants).
final class BrainDumpTests: XCTestCase {
    private func status(_ json: String) throws -> API.Status {
        try JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    func testTheStatusDecodesWhileDumpingAndInReview() throws {
        let dumping = try status(#"{"connected": true, "sessions": [], "brain_dump": {"id": "d1", "state": "dumping", "since": 1, "thoughts": [{"text": "the retry loop has no backoff", "at": 2}], "prompt": null}}"#)
        XCTAssertEqual(dumping.brain_dump?.thoughts.first?.text, "the retry loop has no backoff")
        XCTAssertTrue(dumping.dumping)
        XCTAssertEqual(dumping.brain_dump?.inReview, false)
        let review = try status(#"{"connected": true, "sessions": [], "brain_dump": {"id": "d1", "state": "review", "thoughts": [], "prompt": {"goal": "fix it", "context": [], "constraints": [], "open_questions": [], "text": "Goal: fix it"}, "fallback": true}}"#)
        XCTAssertFalse(review.dumping)
        XCTAssertEqual(review.brain_dump?.inReview, true)
        XCTAssertEqual(review.brain_dump?.prompt?.text, "Goal: fix it")
        XCTAssertEqual(review.brain_dump?.fallback, true)
    }

    func testAnOlderMacSendsNoneAndTheDemoFixturesDecode() throws {
        XCTAssertNil(try status(#"{"connected": true, "sessions": []}"#).brain_dump)
        XCTAssertFalse(try status(#"{"connected": true, "sessions": []}"#).dumping)
        let dump = try XCTUnwrap(Demo.make(.brainDump)).status.brain_dump
        XCTAssertEqual(dump?.state, "dumping")
        XCTAssertEqual(dump?.thoughts.count, 3)
        let review = try XCTUnwrap(Demo.make(.brainDumpReview)).status.brain_dump
        XCTAssertEqual(review?.inReview, true)
        XCTAssertTrue(review?.prompt?.text.hasPrefix("Goal\nstop the checkout") ?? false, "sections as headings, no machine framing")
        XCTAssertFalse(review?.prompt?.text.contains("nothing added") ?? true)
    }

    func testTheButtonReadsBrainDumpThenDoneThenReview() throws {
        XCTAssertEqual(BrainDumpCopy.buttonLabel(nil), "Brain dump")
        let dumping = try XCTUnwrap(Demo.make(.brainDump)).status.brain_dump
        XCTAssertEqual(BrainDumpCopy.buttonLabel(dumping), "Done")
        let review = try XCTUnwrap(Demo.make(.brainDumpReview)).status.brain_dump
        XCTAssertEqual(BrainDumpCopy.buttonLabel(review), "Review")
    }

    private let sessions = ["billing/main", "docs", "river-lantern"]

    func testInOrchestratorModeTheDefaultIsTheOrchestratorListedFirst() throws {
        let dump = try XCTUnwrap(Demo.make(.brainDumpReview)).status.brain_dump!
        XCTAssertEqual(dump.send_to, API.DumpSendTo(orchestrator: true, session: nil, gone: nil))
        XCTAssertEqual(BrainDumpCopy.target(dump, picked: nil, active: "billing/main", sessions: sessions), .orchestrator)
        XCTAssertEqual(BrainDumpCopy.choices(dump, sessions: sessions).map(\.label), ["Orchestrator", "billing/main", "docs", "river-lantern"])
        XCTAssertNil(BrainDumpCopy.goneNote(dump, target: .orchestrator))
    }

    func testInSessionModeTheDefaultIsThePinnedSession() throws {
        let status = try XCTUnwrap(Demo.make(.brainDumpPinned)).status
        let dump = try XCTUnwrap(status.brain_dump)
        XCTAssertEqual(status.mode, "session")
        XCTAssertEqual(BrainDumpCopy.target(dump, picked: nil, active: "billing/main", sessions: sessions), .session("docs"),
                       "where the dump started, not the active session now")
    }

    func testAPickOverridesTheDefaultBothWaysAndAGonePickFallsBack() throws {
        let orchestrated = try XCTUnwrap(Demo.make(.brainDumpReview)).status.brain_dump!
        XCTAssertEqual(BrainDumpCopy.target(orchestrated, picked: .session("docs"), active: nil, sessions: sessions), .session("docs"))
        let pinned = try XCTUnwrap(Demo.make(.brainDumpPinned)).status.brain_dump!
        XCTAssertEqual(BrainDumpCopy.target(pinned, picked: .orchestrator, active: nil, sessions: sessions), .orchestrator)
        XCTAssertEqual(BrainDumpCopy.target(pinned, picked: .session("left"), active: nil, sessions: sessions), .session("docs"),
                       "a pick that is no longer offered gives way to the default")
    }

    func testAPinnedSessionThatIsGoneFallsBackToTheOrchestratorAndSaysSo() throws {
        let dump = try XCTUnwrap(Demo.make(.brainDumpGone)).status.brain_dump!
        let target = BrainDumpCopy.target(dump, picked: nil, active: "billing/main", sessions: sessions)
        XCTAssertEqual(target, .orchestrator)
        XCTAssertEqual(BrainDumpCopy.goneNote(dump, target: target), "old-lantern is gone, so this goes to the orchestrator.")
        XCTAssertNil(BrainDumpCopy.goneNote(dump, target: .session("docs")), "picked a session: the note no longer applies")
    }

    func testAnOlderMacWithoutSendToOffersOnlySessionsAsBefore() throws {
        var dump = try XCTUnwrap(Demo.make(.brainDumpReview)).status.brain_dump!
        dump.send_to = nil  // 1.6.1 sends none, and its send without a session goes to the active one, never the orchestrator
        XCTAssertEqual(BrainDumpCopy.choices(dump, sessions: sessions), sessions.map { .session($0) })
        XCTAssertEqual(BrainDumpCopy.target(dump, picked: nil, active: "billing/main", sessions: sessions), .session("billing/main"))
        dump.target = "river-lantern"
        XCTAssertEqual(BrainDumpCopy.target(dump, picked: nil, active: "billing/main", sessions: sessions), .session("river-lantern"))
        XCTAssertEqual(BrainDumpCopy.target(dump, picked: .orchestrator, active: "billing/main", sessions: sessions), .session("river-lantern"))
        XCTAssertNil(BrainDumpCopy.target(dump, picked: nil, active: nil, sessions: []))
    }

    func testTheCopyIsThePagesWordForWord() {
        XCTAssertEqual(BrainDumpCopy.button, "Brain dump")
        XCTAssertEqual(BrainDumpCopy.lede, "Talk freely. Nothing is sent until you say so.")
        XCTAssertEqual(BrainDumpCopy.reviewTitle, "Your brain dump, structured")
        XCTAssertEqual(BrainDumpCopy.hint, "When you're done: tap Done, or say “done” or “over to you”.")
        XCTAssertEqual(BrainDumpCopy.state, "Brain dump")
        XCTAssertEqual(ChallengeCopy.fromDump, "Challenge it")
        XCTAssertEqual(BrainDumpCopy.to, "To:")
        XCTAssertEqual(BrainDumpCopy.send, "Send")
        XCTAssertEqual(BrainDumpCopy.sendSure, "Tap again to send")
    }
}
