import XCTest
@testable import PointeUI

/// A typed line shows at once and says where it stands (Outbox.swift); the Mac's side, the id that makes a resend
/// safe, is tests/test_bad_network.py.
final class OutboxTests: XCTestCase {
    private func turn(_ id: Int, _ text: String) -> API.Turn {
        API.Turn(id: id, who: "user", text: text, understood: nil, typed: true, corrected: nil)
    }

    func testALineShowsAtOnceAsSendingThenSentThenLeavesWhenTheMacShowsIt() {
        var box = Outbox()
        let line = box.add("ship the hotfix", id: "a")
        XCTAssertEqual(box.lines.map(\.state), [.sending])
        box.sent(line.id, turn: 41)
        XCTAssertEqual(box.line("a")?.state, .sent(turn: 41))
        box.settle([turn(40, "earlier")])  // a status from before the Mac took it
        XCTAssertEqual(box.lines.count, 1)
        box.settle([turn(40, "earlier"), turn(41, "ship the hotfix")])
        XCTAssertTrue(box.lines.isEmpty, "drawn from the Mac's conversation now, once")
    }

    func testALineTheMacDidNotTakeStaysWithItsReasonAndCanBeSentAgain() {
        var box = Outbox()
        box.add("hello", id: "a")
        box.failed("a", why: TypedCopy.noAnswer)
        box.settle([])
        XCTAssertEqual(box.line("a")?.state, .failed(TypedCopy.noAnswer), "a status does not clear a line that was not sent")
        box.sending("a")
        XCTAssertEqual(box.line("a")?.state, .sending)
    }

    func testALineInAMeetingAddsNoTurnAndLeavesAfterTheNextStatus() {
        var box = Outbox()
        box.add("what did Dana say", id: "a")
        box.sent("a", turn: nil)
        box.settle([])
        XCTAssertEqual(box.lines.count, 1, "the status in flight when it was sent may not have it yet")
        box.settle([])
        XCTAssertTrue(box.lines.isEmpty)
    }

    func testLinesKeepTheirOrder() {
        var box = Outbox()
        box.add("one", id: "1")
        box.add("two", id: "2")
        box.sent("2", turn: 8)
        box.settle([turn(8, "two")])
        XCTAssertEqual(box.lines.map(\.text), ["one"])
    }

    /// The Mac's own answer is the same for a resend (daemon.say_by_typing): the waits only bound how long a line
    /// stays Sending on a path that drops requests.
    func testAResendGivesUpWithinAMinute() {
        XCTAssertLessThan(Outbox.resendWaits.reduce(0, +) + Double(Outbox.resendWaits.count + 1) * API.sayTimeout, 50)
        XCTAssertEqual(Outbox.resendWaits.first, 0.5)
    }

    func testThePageSaysTheSameWords() throws {
        let page = try Repo.text("pointe/ui.html")
        for word in [TypedCopy.sending, TypedCopy.sent, TypedCopy.notSent] {  // the page puts an unsent line back in its box
            XCTAssertTrue(page.contains("'\(word)'"), "ui.html's TYPED_COPY says \(word)")
        }
    }
}
