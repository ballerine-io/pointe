import XCTest
@testable import Pointe

/// Whisper mode on the phone: the Mac's status decodes, typing comes forward once when it turns on, the push-to-talk
/// suggestion's "Not now" lasts until whisper mode ends, and the copy is the page's.
final class WhisperTests: XCTestCase {
    private func status(_ json: String) throws -> API.WhisperStatus {
        try JSONDecoder().decode(API.WhisperStatus.self, from: Data(json.utf8))
    }

    func testTheMacsStatusDecodes() throws {
        let on = try status(#"{"on": true, "output_gain": 0.5, "max_words": 20, "suggest_ptt": true, "lock_note": "x"}"#)
        XCTAssertTrue(on.on)
        XCTAssertEqual(on.output_gain, 0.5)
        XCTAssertEqual(on.lock_note, "x")
        let off = try status(#"{"on": false, "output_gain": 1.0, "max_words": null, "suggest_ptt": false, "lock_note": null}"#)
        XCTAssertFalse(off.on)
        XCTAssertNil(off.lock_note)
    }

    func testAnOlderMacWithoutWhisperModeDecodesAsNil() throws {
        let s = try JSONDecoder().decode(API.Status.self, from: Data(#"{"connected": true, "sessions": []}"#.utf8))
        XCTAssertNil(s.whisper)
    }

    func testTypingComesForwardOnceWhenWhisperModeTurnsOn() throws {
        let on = try status(#"{"on": true}"#), off = try status(#"{"on": false}"#)
        var follow = WhisperFollow()
        XCTAssertFalse(follow.follow(off), "off at the first look: nothing opens")
        XCTAssertTrue(follow.follow(on), "turned on (here, on the page or by voice): typing opens")
        XCTAssertFalse(follow.follow(on), "still on: not again, so closing the keyboard sticks")
        XCTAssertFalse(follow.follow(off))
        XCTAssertTrue(follow.follow(on))
        var fresh = WhisperFollow()
        XCTAssertTrue(fresh.follow(on), "already on when the app opens: typing is shown by default")
        var none = WhisperFollow()
        XCTAssertFalse(none.follow(nil), "a Mac without the feature")
    }

    func testNotNowHidesThePushToTalkSuggestionUntilWhisperModeEnds() throws {
        let suggest = try status(#"{"on": true, "suggest_ptt": true}"#)
        var follow = WhisperFollow()
        _ = follow.follow(suggest)
        XCTAssertTrue(follow.suggestsPushToTalk(suggest))
        follow.notNow()
        XCTAssertFalse(follow.suggestsPushToTalk(suggest))
        _ = follow.follow(try status(#"{"on": false}"#))
        _ = follow.follow(suggest)
        XCTAssertTrue(follow.suggestsPushToTalk(suggest), "the next whisper mode asks again")
        XCTAssertFalse(follow.suggestsPushToTalk(try status(#"{"on": true, "suggest_ptt": false}"#)), "push to talk is already on")
    }

    /// The page and the app say the same thing (docs/plans/next-features.md: parity).
    func testTheCopyIsThePagesWordForWord() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let html = try String(contentsOf: root.appendingPathComponent("ui_whisper.html"), encoding: .utf8)
        let ui = try String(contentsOf: root.appendingPathComponent("ui.html"), encoding: .utf8)
        for copy in [WhisperCopy.title, WhisperCopy.limit, WhisperCopy.suggest, WhisperCopy.turnOn, WhisperCopy.notNow,
                     WhisperCopy.back, WhisperCopy.failed, WhisperCopy.buttonOn] {
            XCTAssertTrue(html.contains(copy), "the page says: \(copy)")
        }
        XCTAssertTrue(ui.contains(">\(WhisperCopy.button)</span>"), "the dock button")
        let daemon = try String(contentsOf: root.appendingPathComponent("whisper.py"), encoding: .utf8)
            .replacingOccurrences(of: "\"\\s*\n\\s*\"", with: "", options: .regularExpression)
        XCTAssertTrue(daemon.contains("A whispered yes may not match it: then tap to approve."), "the lock note comes from the Mac")
    }
}
