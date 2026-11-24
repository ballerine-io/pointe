import XCTest
@testable import PointeUI

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

    func testDriveModeHoldsIt() throws {
        let held = try status(#"{"on": true, "held": "drive", "suggest_ptt": false}"#)
        var follow = WhisperFollow()
        XCTAssertEqual(held.held, "drive")
        XCTAssertFalse(follow.follow(held), "held by drive mode: no typing forward")
        XCTAssertFalse(follow.suggestsPushToTalk(held))
        XCTAssertTrue(follow.follow(try status(#"{"on": true}"#)), "drive mode ended: whisper mode applies again")
    }

    /// Folded to its title when the dock leaves less than the whole card; whole again when asked, or when the room is back.
    func testTheCardFoldsOnlyWhenItWouldNotFit() {
        XCTAssertTrue(WhisperCopy.folds(room: 40, whole: 150, asked: false), "an iPhone SE with the keyboard up")
        XCTAssertFalse(WhisperCopy.folds(room: 40, whole: 150, asked: true), "Show notes was tapped")
        XCTAssertFalse(WhisperCopy.folds(room: 400, whole: 150, asked: false), "room for all of it")
        XCTAssertFalse(WhisperCopy.folds(room: .infinity, whole: 150, asked: false), "no dock limit")
        XCTAssertFalse(WhisperCopy.folds(room: 40, whole: 0, asked: false), "not measured yet: whole")
    }

    /// The page and the app say the same thing (docs/design/parity.md).
    func testTheCopyIsThePagesWordForWord() throws {
        let html = try Repo.text("pointe/ui_whisper.html")
        let ui = try Repo.text("pointe/ui.html")
        for copy in [WhisperCopy.title, WhisperCopy.limit, WhisperCopy.suggest, WhisperCopy.turnOn, WhisperCopy.notNow,
                     WhisperCopy.back, WhisperCopy.failed, WhisperCopy.buttonOn] {
            XCTAssertTrue(html.contains(copy), "the page says: \(copy)")
        }
        XCTAssertTrue(ui.contains(">\(WhisperCopy.button)</span>"), "the dock button")
        let daemon = try Repo.text("pointe/whisper.py")
            .replacingOccurrences(of: "\"\\s*\n\\s*\"", with: "", options: .regularExpression)
        XCTAssertTrue(daemon.contains("A whispered yes may not match it: then tap to approve."), "the lock note comes from the Mac")
    }
}
