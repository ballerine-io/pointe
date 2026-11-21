import XCTest
@testable import PointeUI

final class TalkGateTests: XCTestCase {
    private let t0 = Date(timeIntervalSince1970: 1_000)

    private func ptt() -> TalkGate { var g = TalkGate(); g.mode = "ptt"; return g }

    private func status(_ json: String) -> API.PTTStatus {
        try! JSONDecoder().decode(API.PTTStatus.self, from: Data(json.utf8))
    }

    func testAlwaysOnSendsEverythingAndIgnoresPresses() {
        var g = TalkGate()
        XCTAssertTrue(g.sends(at: t0))
        g.press(.ring, at: t0)
        XCTAssertFalse(g.isOpen)
    }

    func testPushToTalkSendsNothingUntilHeld() {
        var g = ptt()
        XCTAssertFalse(g.sends(at: t0))
        g.press(.ring, at: t0)
        XCTAssertTrue(g.isOpen)
        XCTAssertTrue(g.sends(at: t0))
    }

    func testOpenWhileAnyHoldIsDown() {
        var g = ptt()
        g.press(.ring, at: t0)
        g.press(.caption, at: t0)
        g.release(.ring, at: t0)
        XCTAssertTrue(g.isOpen, "the caption is still held")
        g.release(.caption, at: t0)
        XCTAssertFalse(g.isOpen)
    }

    func testTheTailKeepsSendingAfterARelease() {
        var g = ptt()
        g.press(.ring, at: t0)
        g.release(.ring, at: t0)
        XCTAssertTrue(g.sends(at: t0.addingTimeInterval(TalkGate.tail - 0.05)))
        XCTAssertFalse(g.sends(at: t0.addingTimeInterval(TalkGate.tail + 0.05)))
    }

    func testAToggleOpensAndClosesAndTheLastEventWins() {
        var g = ptt()
        g.toggle(at: t0)
        XCTAssertTrue(g.isOpen)
        g.press(.ring, at: t0)
        g.release(.ring, at: t0)  // the ring let go last: closed, even though the AirPods had opened it
        XCTAssertFalse(g.isOpen)
        g.press(.ring, at: t0)
        g.toggle(at: t0)  // the AirPods pressed last while the ring is held: closed
        XCTAssertFalse(g.isOpen)
        g.release(.ring, at: t0)
        XCTAssertFalse(g.isOpen)
    }

    func testTheMacClosingAPressItShowedOpenClosesItHere() {
        var g = ptt()
        g.press(.ring, at: t0)
        XCTAssertNil(g.follow(status(#"{"mode":"ptt","open":false,"closed_why":"held too long"}"#)),
                     "an earlier press's close, before the Mac showed this one open")
        XCTAssertTrue(g.isOpen)
        XCTAssertNil(g.follow(status(#"{"mode":"ptt","open":true,"closed_why":""}"#)))
        XCTAssertEqual(g.follow(status(#"{"mode":"ptt","open":false,"closed_why":"held too long"}"#)), "held too long")
        XCTAssertFalse(g.isOpen)
        XCTAssertFalse(g.sends(at: t0), "the Mac's gate is shut: no tail")
    }

    func testAReleasedCloseDoesNotCloseANewPress() {
        var g = ptt()
        g.press(.ring, at: t0)
        _ = g.follow(status(#"{"open":true}"#))
        XCTAssertNil(g.follow(status(#"{"open":false,"closed_why":"released"}"#)))
        XCTAssertTrue(g.isOpen)
    }

    func testAReconnectStartsClosed() {
        var g = ptt()
        g.toggle(at: t0)
        g.reset()
        XCTAssertFalse(g.isOpen)
        XCTAssertFalse(g.sends(at: t0))
    }

    func testTheControlMessage() throws {
        let text = TalkGate.message(open: true, at: Date(timeIntervalSince1970: 12.5))
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any])
        XCTAssertEqual(json["type"] as? String, "ptt")
        XCTAssertEqual(json["open"] as? Bool, true)
        XCTAssertEqual(json["at"] as? Int, 12_500)
    }

    func testInAMeetingTheRoomIsSentWithoutAPressAndStopsAfter() {
        var g = ptt()
        XCTAssertFalse(g.sends(at: t0))
        _ = g.follow(status(#"{"mode":"ptt","open":false,"closed_why":"","room_heard":true}"#))
        XCTAssertTrue(g.roomHeard)
        XCTAssertTrue(g.sends(at: t0))
        XCTAssertFalse(g.isOpen)  // the room is heard; the user is not talking to Pointe
        _ = g.follow(status(#"{"mode":"ptt","open":false,"closed_why":"","room_heard":false}"#))
        XCTAssertFalse(g.sends(at: t0))
    }

    func testTheRingShowsThePhonesPressAndTheMacsGateOnlyWhileItHoldsNone() {
        var g = ptt()
        XCTAssertTrue(g.shows(macOpen: true), "no press of its own yet: the Mac's open gate shows (a shortcut, the demo)")
        XCTAssertFalse(g.shows(macOpen: false))
        g.press(.ring, at: t0)
        XCTAssertTrue(g.shows(macOpen: false), "the press shows at the touch, before the Mac's status")
        g.release(.ring, at: t0.addingTimeInterval(1))
        XCTAssertFalse(g.shows(macOpen: true), "the status still says open after a lift: the lift wins, and a new press is not swallowed")
        g.press(.ring, at: t0.addingTimeInterval(1.1))
        XCTAssertTrue(g.isOpen && g.shows(macOpen: true))
        g.reset()
        XCTAssertTrue(g.shows(macOpen: true), "a new call: nothing let go yet")
    }

    func testTheLinesForAPressTheMacClosedAreThePages() {
        XCTAssertEqual(TalkGate.closedLine("held too long", style: .hold), "Talk closed after 90 s: press again")
        XCTAssertEqual(TalkGate.closedLine("held too long", style: .tap), "Talk closed after 90 s: tap again")
        XCTAssertEqual(TalkGate.closedLine("no audio", style: .tap), "Talk closed: no audio reached the Mac")
    }

    func testTheMacsShortcutOpensAndClosesThePressAndIsIgnoredWhenAlwaysOn() {
        var g = ptt()
        g.set(open: true, at: t0)
        XCTAssertTrue(g.isOpen)
        XCTAssertTrue(g.sends(at: t0))
        g.set(open: true, at: t0)  // said again: still the one press
        XCTAssertTrue(g.isOpen)
        g.set(open: false, at: t0)
        XCTAssertFalse(g.isOpen)
        var always = TalkGate()
        always.set(open: true, at: t0)
        XCTAssertFalse(always.isOpen, "always on: the Mac's gate takes no press, and the phone shows none")
    }

    func testStatusAndPrefsDecodeWithAndWithoutPushToTalk() throws {
        let prefs = try JSONDecoder().decode(API.Prefs.self, from: Data(#"{"microphone":"ptt"}"#.utf8))
        XCTAssertEqual(prefs.microphone, "ptt")
        XCTAssertEqual(try JSONDecoder().decode(API.Prefs.self, from: Data("{}".utf8)).microphone, "always")
        let old = try JSONDecoder().decode(API.Status.self, from: Data(#"{"connected":true,"sessions":[]}"#.utf8))
        XCTAssertNil(old.ptt)
    }
}

final class TalkShortcutTests: XCTestCase {
    func testThePressTogglesOnALiveCallInPushToTalkAndOtherwiseSaysWhy() {
        XCTAssertEqual(TalkShortcut.decide(call: .live, ptt: true), .toggle)
        XCTAssertEqual(TalkShortcut.decide(call: .live, ptt: false), .alwaysOn)
        XCTAssertEqual(TalkShortcut.decide(call: nil, ptt: true), .noCall, "no call: the app opens with a notice")
        XCTAssertEqual(TalkShortcut.decide(call: .connecting, ptt: true), .noCall)
        XCTAssertEqual(TalkShortcut.decide(call: .reconnecting, ptt: true), .noCall)
    }
}

/// Hold or tap: the device's choice, with the page's words (tests/test_ptt_modes.py reads both).
final class TalkStyleTests: XCTestCase {
    func testStoredPerDeviceAndHoldByDefault() {
        let defaults = UserDefaults(suiteName: "TalkStyleTests")!
        defaults.removePersistentDomain(forName: "TalkStyleTests")
        XCTAssertEqual(TalkStyle.stored(in: defaults), .hold)
        defaults.set("tap", forKey: TalkStyle.key)
        XCTAssertEqual(TalkStyle.stored(in: defaults), .tap)
        defaults.set("lean", forKey: TalkStyle.key)
        XCTAssertEqual(TalkStyle.stored(in: defaults), .hold, "an unknown value is the default, not a crash")
    }

    func testTheWordsAreThePages() {
        XCTAssertEqual(TalkStyle.allCases.map(\.rawValue), ["hold", "tap"])
        XCTAssertEqual(TalkStyle.hold.label, "Hold to talk")
        XCTAssertEqual(TalkStyle.tap.label, "Tap to talk")
        XCTAssertEqual(TalkStyle.hold.talkingLine, "Talking")
        XCTAssertEqual(TalkStyle.tap.talkingLine, "Talking · tap to send")
        XCTAssertEqual(TalkStyle.sentLine, "Sent")
        XCTAssertEqual(TalkStyle.shortPressLine, "Hold to talk · or choose Tap to talk in Settings")
        XCTAssertEqual(TalkStyle.shortPress, 0.25)
    }
}

/// A press is one message: its words show as a draft until the Mac sends them (tests/test_ptt_message.py holds the page's).
final class TalkDraftTests: XCTestCase {
    func testThePressDraftIsLabelledUntilItIsSent() {
        XCTAssertEqual(TalkDraft.line(draft: true, open: true), "Draft · not sent yet")
        XCTAssertEqual(TalkDraft.line(draft: true, open: false), "Sending", "closed: the last words are being finalized")
        XCTAssertNil(TalkDraft.line(draft: false, open: true), "sent, or always on: the usual live bubble")
        XCTAssertNil(TalkDraft.line(draft: nil, open: true), "an older Mac says nothing about drafts")
    }

    func testTheDraftFlagDecodesAndAnOlderMacSendsNone() throws {
        let now = try JSONDecoder().decode(API.PTTStatus.self, from: Data(#"{"mode":"ptt","open":true,"draft":true}"#.utf8))
        XCTAssertEqual(now.draft, true)
        let old = try JSONDecoder().decode(API.PTTStatus.self, from: Data(#"{"mode":"ptt","open":true}"#.utf8))
        XCTAssertNil(old.draft)
    }
}
