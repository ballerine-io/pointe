import XCTest
@testable import Pointe

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

    func testStatusAndPrefsDecodeWithAndWithoutPushToTalk() throws {
        let prefs = try JSONDecoder().decode(API.Prefs.self, from: Data(#"{"microphone":"ptt"}"#.utf8))
        XCTAssertEqual(prefs.microphone, "ptt")
        XCTAssertEqual(try JSONDecoder().decode(API.Prefs.self, from: Data("{}".utf8)).microphone, "always")
        let old = try JSONDecoder().decode(API.Status.self, from: Data(#"{"connected":true,"sessions":[]}"#.utf8))
        XCTAssertNil(old.ptt)
    }
}
