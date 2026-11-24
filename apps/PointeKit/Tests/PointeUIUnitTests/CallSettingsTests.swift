import XCTest
@testable import PointeUI

/// Settings is built from a value compared as a whole: a status poll that changes nothing it shows leaves it alone. The
/// Menu it replaced was built again on every poll, and jumped back to its top while you scrolled it.
@MainActor
final class CallSettingsTests: XCTestCase {
    private func status(hearing: String, lastLine: Int, sentBytes: Int, polish: Bool = false, whisper: Bool = false) -> API.Status {
        let talk = (1...lastLine).map { #"{"id": \#($0), "who": "assistant", "text": "line \#($0)"}"# }.joined(separator: ",")
        let json = """
        {"connected": true, "mode": "orchestrator", "polish": \(polish), "hearing": "\(hearing)", "talk": [\(talk)],
         "sessions": [{"name": "billing", "working": true, "waiting": false, "needs": null}],
         "ptt": {"mode": "ptt", "open": true, "closed_why": "", "sent_bytes": \(sentBytes)},
         "whisper": {"on": \(whisper), "output_gain": 1.0, "max_words": null, "suggest_ptt": false, "lock_note": null},
         "machines": [{"id": "hub", "name": "studio", "here": true, "os": "macos", "online": true, "sessions": 1, "need": 0}]}
        """
        return try! JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    private func model(_ status: API.Status, microphone: String = "ptt") -> CallSettingsModel {
        CallSettingsModel(status: status, prefs: nil, microphone: microphone, talkStyle: .hold, live: true, dumping: false,
                          driving: false, driveSuggest: false, demo: false)
    }

    func testAPollThatChangesOnlyTheConversationLeavesSettingsAlone() {
        let before = model(status(hearing: "ask billing", lastLine: 3, sentBytes: 1_000))
        let after = model(status(hearing: "ask billing whether the retry", lastLine: 4, sentBytes: 9_000))
        XCTAssertEqual(before, after)
        XCTAssertEqual(CallSettingsSheet(model: before), CallSettingsSheet(model: after), "so the sheet is not built again")
    }

    func testAChangeSettingsShowsIsAChange() {
        let base = status(hearing: "", lastLine: 3, sentBytes: 0)
        XCTAssertNotEqual(model(base), model(status(hearing: "", lastLine: 3, sentBytes: 0, polish: true)), "Clean up my words")
        XCTAssertNotEqual(model(base), model(status(hearing: "", lastLine: 3, sentBytes: 0, whisper: true)), "Whisper")
        XCTAssertNotEqual(model(base), model(base, microphone: "always"), "the microphone")
    }

    /// The actions are closures, new on every render of the call: they take no part in the comparison.
    func testTheActionsAreNotCompared() {
        let m = model(status(hearing: "", lastLine: 1, sentBytes: 0))
        var calls = 0
        let a = CallSettingsSheet(model: m, act: CallSettingsActions(open: { _ in calls += 1 }))
        let b = CallSettingsSheet(model: m, act: CallSettingsActions(open: { _ in calls += 2 }))
        XCTAssertEqual(a, b)
    }

    func testWhatTheMacHasDecidesTheRows() {
        let m = model(status(hearing: "", lastLine: 1, sentBytes: 0))
        XCTAssertEqual(m.whisper, false, "the Mac has whisper mode: its switch shows, off")
        XCTAssertTrue(m.machines)
        XCTAssertFalse(m.voiceLock, "no voice lock in this status: no row")
        XCTAssertTrue(m.challengeOpen, "a live call with nothing else on")
    }
}
