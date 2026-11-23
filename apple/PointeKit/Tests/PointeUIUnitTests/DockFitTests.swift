#if os(macOS)
import AppKit
import PointeKit
import SwiftUI
import XCTest
@testable import PointeUI

/// A card over the bar whose answer is a button (Start shift, Start, Ask and Dismiss) is never taller than the room the
/// dock leaves it: a long read-back scrolls inside the card and the buttons stay in view. Round 3 found Start shift and
/// Cancel under the bar in a short Mac window, and the conflict card's buttons below the cut at large text.
@MainActor
final class DockFitTests: XCTestCase {
    private let room: CGFloat = 200
    private let long = Array(repeating: "billing: finish the retry work and open a pull request for review.", count: 8).joined(separator: " ")

    func testALongNightShiftReadBackKeepsStartShiftInTheRoom() {
        let card = ShiftCard(pending: shift(long)) { _, _ in }
        XCTAssertLessThanOrEqual(height(of: card), room + 1)
    }

    func testALongStartReadBackKeepsStartInTheRoom() {
        let card = StartCard(pending: NewSession.Pending(id: "n1", line: long)) { _, _ in }
        XCTAssertLessThanOrEqual(height(of: card), room + 1)
    }

    func testALongConflictKeepsAskAndDismissInTheRoom() throws {
        let json = """
        {"id": "c1", "a": "river-lantern", "b": "billing/main", "claim_a": "\(long)", "claim_b": "\(long)",
         "why": "They disagree on the retry budget."}
        """
        let conflict = try JSONDecoder().decode(API.Conflict.self, from: Data(json.utf8))
        let card = ConflictCard(conflict: conflict, inMeeting: false, live: true) { _, _ in nil }
        XCTAssertLessThanOrEqual(height(of: card), room + 1)
    }

    /// With room to spare a short card is its own height: the limit only bites when the room runs out.
    func testAShortCardIsItsOwnHeight() {
        let short = height(of: ShiftCard(pending: shift("Night shift. docs: update the changelog.")) { _, _ in })
        XCTAssertLessThan(short, room)
        XCTAssertGreaterThan(short, 100)
    }

    private func shift(_ line: String) -> NightShift.Pending {
        try! JSONDecoder().decode(NightShift.Pending.self, from: JSONEncoder().encode(["id": "s1", "line": line]))
    }

    /// Laid out at 380 points wide in the given room, a few passes so the measured heights settle, as on screen.
    private func height(of card: some View) -> CGFloat {
        let host = NSHostingView(rootView: card.environment(\.dockRoom, room).frame(width: 380).fixedSize(horizontal: false, vertical: true))
        host.frame = NSRect(x: 0, y: 0, width: 380, height: 2000)
        for _ in 0..<6 {
            host.layoutSubtreeIfNeeded()
            RunLoop.main.run(until: Date().addingTimeInterval(0.05))
        }
        return host.fittingSize.height
    }
}
#endif
