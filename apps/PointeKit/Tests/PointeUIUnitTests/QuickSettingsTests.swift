import XCTest
@testable import PointeUI

/// Quick settings (QuickSettings.swift): what the row and the sheet show from a status, what a tap sends, and when a chip
/// glows after a change by voice. The words themselves are checked against the page's and the daemon's in
/// tests/test_quick_page.py.
@MainActor
final class QuickSettingsTests: XCTestCase {
    private func status(quick: String? = #"{"length": "detailed", "speeds": {"mac": 0.9, "iphone": 1.1}, "speed_shown": true, "by_voice": null}"#,
                        polish: Bool = false, whisper: String? = #"{"on": false, "output_gain": 1.0, "max_words": null, "suggest_ptt": false, "lock_note": null}"#) -> API.Status {
        let json = """
        {"connected": true, "mode": "orchestrator", "polish": \(polish), "sessions": []
         \(quick.map { #", "quick": \#($0)"# } ?? "")\(whisper.map { #", "whisper": \#($0)"# } ?? "")}
        """
        return try! JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    func testTheRowShowsTheMacsValuesAndThisDevicesOwnSpeed() {
        let model = QuickModel(status: status(), microphone: "ptt")
        XCTAssertTrue(model.available)
        XCTAssertEqual(model.length, "detailed")
        XCTAssertEqual(model.speed, QuickRule.surface == "mac" ? 0.9 : 1.1, "each device has its own speed")
        XCTAssertTrue(model.speedShown)
        XCTAssertEqual(model.whisper, false)
        XCTAssertEqual(model.microphone, "ptt")
    }

    func testAMacBeforeQuickSettingsShowsOnlyTheToggles() {
        let model = QuickModel(status: status(quick: nil, whisper: nil), microphone: "always")
        XCTAssertFalse(model.available)
        XCTAssertFalse(model.speedShown)
        XCTAssertNil(model.whisper, "no whisper mode on that Mac: no whisper chip")
        XCTAssertEqual(model.length, QuickRule.defaultLevel)
    }

    func testAVoiceWithNoSpeedNumberHidesTheSpeed() {
        let model = QuickModel(status: status(quick: #"{"length": "concise", "speeds": {}, "speed_shown": false, "by_voice": null}"#), microphone: "always")
        XCTAssertFalse(model.speedShown)
        XCTAssertEqual(model.speed, 1)
    }

    func testTheSpeedChipSaysTheSpeedLikeTheMockups() {
        XCTAssertEqual(QuickRule.speeds.map { QuickRule.speedLabel($0.value) }, ["0.8×", "0.9×", "1×", "1.1×", "1.2×"])
        XCTAssertEqual(QuickRule.speeds.map(\.name), ["Slowest", "Slower", "Normal", "Faster", "Fastest"])
        XCTAssertEqual(QuickRule.levels.map(\.value), ["brief", "concise", "detailed", "thorough"])
        XCTAssertEqual(QuickRule.speed(1.1).hint, QuickCopy.fasterHint)
    }

    func testTheDotMeansAQuickSettingIsOffItsDefault() {
        var model = QuickModel(status: status(quick: #"{"length": "concise", "speeds": {}, "speed_shown": true, "by_voice": null}"#), microphone: "always")
        XCTAssertFalse(QuickRule.offDefault(model))
        for change in [{ (m: inout QuickModel) in m.length = "brief" }, { $0.speed = 1.1 }, { $0.polish = true }, { $0.whisper = true }] {
            var changed = model
            change(&changed)
            XCTAssertTrue(QuickRule.offDefault(changed))
        }
        model.microphone = "ptt"
        XCTAssertFalse(QuickRule.offDefault(model), "the microphone is not a quick setting on the iPhone")
    }

    func testAChangeByVoiceGlowsOnceAndOnlyWhileFresh() {
        let now = Date()
        let fresh = API.QuickStatus.ByVoice(key: "replies.length", at: now.timeIntervalSince1970 - 1)
        XCTAssertEqual(QuickRule.glow(seen: nil, now: fresh, at: now), "replies.length")
        XCTAssertNil(QuickRule.glow(seen: fresh, now: fresh, at: now), "the same change again is not a new one")
        XCTAssertNil(QuickRule.glow(seen: nil, now: API.QuickStatus.ByVoice(key: "polish", at: now.timeIntervalSince1970 - 30), at: now),
                     "a screen that opens later does not glow for an old change")
        XCTAssertNil(QuickRule.glow(seen: fresh, now: nil, at: now))
    }

    func testATapSendsOnlyThisDevicesSpeed() {
        let prefs = QuickChange.speed(1.2).prefs
        XCTAssertEqual(prefs["voice.speed"] as? [String: Double], [QuickRule.surface: 1.2])
        XCTAssertEqual(QuickChange.length("brief").prefs["replies.length"] as? String, "brief")
        XCTAssertEqual(QuickChange.polish(true).prefs["polish"] as? Bool, true)
        XCTAssertEqual(QuickChange.whisper(false).prefs["whisper"] as? Bool, false)
    }

    func testTheRowMovesAtTheTap() {
        var s: API.Status? = status()
        QuickChange.length("thorough").apply(to: &s)
        QuickChange.speed(1.2).apply(to: &s)
        QuickChange.polish(true).apply(to: &s)
        QuickChange.whisper(true).apply(to: &s)
        let model = QuickModel(status: s, microphone: "always")
        XCTAssertEqual([model.length, QuickRule.speedLabel(model.speed)], ["thorough", "1.2×"])
        XCTAssertTrue(model.polish)
        XCTAssertEqual(model.whisper, true)
        XCTAssertEqual(s?.quick?.speeds?[QuickRule.surface == "mac" ? "iphone" : "mac"], QuickRule.surface == "mac" ? 1.1 : 0.9,
                       "the other device keeps its own")
    }

    func testEveryDemoHasQuickSettings() {
        XCTAssertEqual(Demo.make(.call)?.status.quick, .demo)
    }

    func testNoEmDashInTheWords() {
        let words = QuickRule.levels.flatMap { [$0.name, $0.hint] } + QuickRule.speeds.flatMap { [$0.name, $0.hint] }
            + [QuickCopy.lengthSay, QuickCopy.speedSay, QuickCopy.sheetSay, QuickCopy.polishHint, QuickCopy.title]
        XCTAssertFalse(words.contains { $0.contains("—") })
    }
}
