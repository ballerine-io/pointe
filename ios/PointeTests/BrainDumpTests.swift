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

    func testTheSendTargetIsTheNamedThenThePickedThenTheActiveSession() throws {
        var dump = try XCTUnwrap(Demo.make(.brainDumpReview)).status.brain_dump!
        let sessions = ["billing/main", "docs", "river-lantern"]
        XCTAssertEqual(BrainDumpCopy.target(dump, picked: nil, active: "billing/main", sessions: sessions), "billing/main")
        XCTAssertEqual(BrainDumpCopy.target(dump, picked: "docs", active: "billing/main", sessions: sessions), "docs")
        dump.target = "river-lantern"
        XCTAssertEqual(BrainDumpCopy.target(dump, picked: "docs", active: "billing/main", sessions: sessions), "river-lantern")
        dump.target = "gone"
        XCTAssertEqual(BrainDumpCopy.target(dump, picked: nil, active: "gone", sessions: sessions), "billing/main", "an unknown name falls back to the first")
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
