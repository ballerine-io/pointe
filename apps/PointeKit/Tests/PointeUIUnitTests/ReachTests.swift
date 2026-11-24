import LocalAuthentication
import XCTest
@testable import PointeUI

/// What keeps a control in reach when the room is short (QA round 5): the request card's command box gives up height, a
/// box cut short says so, and Approve says why it did nothing.
final class ReachTests: XCTestCase {
    func testTheCommandBoxGivesUpHeightToTheAnswerButtons() {
        XCTAssertEqual(RequestCard.commandLimit(room: .infinity, chrome: 180), 150, "no dock limit: the usual box")
        XCTAssertEqual(RequestCard.commandLimit(room: 600, chrome: 180), 150, "room to spare: never taller than 150")
        XCTAssertEqual(RequestCard.commandLimit(room: 280, chrome: 180), 100, "short: the box takes only what the rest leaves")
        XCTAssertEqual(RequestCard.commandLimit(room: 150, chrome: 180), 56, "never under two lines: the command is what Approve runs")
        XCTAssertEqual(RequestCard.commandLimit(room: 280, chrome: 0), 150, "not measured yet: the usual box")
    }

    func testAScrolledBoxKnowsWhatItHides() {
        let content = CGSize(width: 300, height: 500)
        XCTAssertEqual(ScrollMore(visible: CGRect(x: 0, y: 0, width: 300, height: 500), content: content), ScrollMore())
        XCTAssertEqual(ScrollMore(visible: CGRect(x: 0, y: 0, width: 300, height: 200), content: content), ScrollMore(below: true))
        XCTAssertEqual(ScrollMore(visible: CGRect(x: 0, y: 300, width: 300, height: 200), content: content), ScrollMore(above: true),
                       "rested on its bottom, as the dock does: the card's top is what is hidden")
        XCTAssertEqual(ScrollMore(visible: CGRect(x: 0, y: 100, width: 300, height: 200), content: content), ScrollMore(above: true, below: true))
    }

    /// Approve returned silently when the owner check could not run: the demo asked for a passcode the simulator lacks.
    func testApproveSaysWhyItDidNothing() {
        XCTAssertNil(OwnerCopy.refusal(.userCancel), "cancelled: the person knows")
        XCTAssertNil(OwnerCopy.refusal(.systemCancel))
        XCTAssertEqual(OwnerCopy.refusal(.passcodeNotSet), OwnerCopy.noPasscode)
        XCTAssertEqual(OwnerCopy.refusal(.authenticationFailed), OwnerCopy.noMatch)
        XCTAssertEqual(OwnerCopy.refusal(.biometryLockout), OwnerCopy.notChecked)
        XCTAssertEqual(OwnerCopy.refusal(nil), OwnerCopy.notChecked, "an error that is not LocalAuthentication's")
        for line in [OwnerCopy.noPasscode, OwnerCopy.noMatch, OwnerCopy.notChecked] { XCTAssertTrue(line.hasPrefix("Not approved")) }
    }

    /// "/pointe:voice" broke after its slash in the sidebar, the empty sessions card and the setup guide.
    func testASlashCommandIsKeptWhole() {
        let line = "Run /pointe:voice in a Claude Code session.".unbrokenCommands
        XCTAssertTrue(line.contains("/\u{2060}pointe:voice"))
        XCTAssertEqual(line.replacingOccurrences(of: "\u{2060}", with: ""), "Run /pointe:voice in a Claude Code session.", "nothing else changes")
    }

    /// The Mac says click where the phone says tap, in the words it draws from the phone's (and the daemon's read-backs).
    func testTheMacClicksWhereThePhoneTaps() {
        XCTAssertEqual(Surface.pointer("Start? Say yes or tap."), Surface.isMac ? "Start? Say yes or click." : "Start? Say yes or tap.")
        XCTAssertEqual(Surface.pointer("Tap again to send"), Surface.isMac ? "Click again to send" : "Tap again to send")
        XCTAssertEqual(Surface.pointer("tapped twice"), "tapped twice", "a whole word only")
    }
}
