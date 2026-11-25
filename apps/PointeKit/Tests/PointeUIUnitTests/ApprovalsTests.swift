import XCTest
@testable import PointeUI

/// The approvals record (docs/features/approvals-record.md): what the Mac's `GET /voice/approvals` sends, decoded, and
/// the words of a row. The same fixture journal the daemon's tests read is what the endpoint was asked for here
/// (Fixtures/approvals.json: its answer to tests/fixtures/approvals_journal.jsonl).
final class ApprovalsTests: XCTestCase {
    private func page() throws -> API.ApprovalsPage {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "approvals", withExtension: "json", subdirectory: "Fixtures"))
        return try JSONDecoder().decode(API.ApprovalsPage.self, from: Data(contentsOf: url))
    }

    func testEveryApprovalTheMacSendsIsARowNewestFirst() throws {
        let rows = try page().approvals
        XCTAssertEqual(rows.map(\.request_id), ["p5", "p4", "p3", "p2", "p1"])
        XCTAssertEqual(Set(rows.map(\.id)).count, 5, "each row is its own")
        XCTAssertEqual(rows.map(\.request_id), Demo.approvals.map(\.request_id), "the demo shows the same record")
    }

    func testARowSaysWhenHowTheExactRequestAndTheScore() throws {
        let first = try XCTUnwrap(page().approvals.last)
        XCTAssertEqual(ApprovalsCopy.head(first), "Approved by voice")
        XCTAssertEqual(ApprovalsCopy.when(first.at), "20 Nov, 09:14")
        XCTAssertEqual(first.request, "Bash\ngit push --force-with-lease origin retry-fix", "word for word")
        XCTAssertEqual(ApprovalsCopy.lock(first), "Voice lock approvals: score 0.71")
        XCTAssertEqual(ApprovalsCopy.spoken(first),
                       "Approved by voice, bluebell/dev, 20 Nov, 09:14, Bash\ngit push --force-with-lease origin retry-fix, Voice lock approvals: score 0.71")
    }

    func testATapHasNoScoreAndAVoiceWithTheLockOffSaysSo() throws {
        let rows = try page().approvals
        let tap = try XCTUnwrap(rows.first { $0.request_id == "p2" })
        XCTAssertEqual(ApprovalsCopy.head(tap), "Denied by a tap")
        XCTAssertNil(ApprovalsCopy.lock(tap), "a tap has no voice to score")
        let unlocked = try XCTUnwrap(rows.first { $0.request_id == "p4" })
        XCTAssertEqual(ApprovalsCopy.lock(unlocked), ApprovalsCopy.lockOff)
        let notified = try XCTUnwrap(rows.first { $0.request_id == "p3" })
        XCTAssertEqual(ApprovalsCopy.head(notified), "Approved from a notification")
        XCTAssertTrue(ApprovalsCopy.spoken(notified).contains("docs on devbox"))
        XCTAssertEqual(rows.first?.cut, true)
    }

    func testAVoiceTheLockDidNotScoreSaysSoAndAnOddClockIsShownAsItIs() throws {
        let odd = try JSONDecoder().decode(API.Approval.self, from: Data(#"{"at": "soon", "session": "a", "request_id": "r", "decision": "deny", "by": "voice", "request": "x", "lock": "approvals"}"#.utf8))
        XCTAssertEqual(ApprovalsCopy.lock(odd), "Voice lock approvals: the voice was not scored")
        XCTAssertEqual(ApprovalsCopy.when(odd.at), "soon")
        XCTAssertEqual(ApprovalsCopy.head(odd), "Denied by voice")
    }
}
