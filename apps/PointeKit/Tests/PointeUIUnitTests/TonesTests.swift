import XCTest
@testable import PointeUI

/// One sound per session (docs/features/session-tones.md): the Mac makes the sound; the apps have the setting, off
/// unless turned on, and name a session's tone beside its agent.
final class TonesTests: XCTestCase {
    func testTheSettingIsOffUnlessTheMacSaysOnAndAbsentOnAnOlderMac() throws {
        let off = try JSONDecoder().decode(API.Prefs.self, from: Data(#"{"reports.tones": false}"#.utf8))
        XCTAssertEqual(off.sessionTones, false)
        let model = CallSettingsModel(status: nil, prefs: off, microphone: "always", talkStyle: .hold, live: true, dumping: false,
                                      driving: false, driveSuggest: false, demo: false)
        XCTAssertEqual(model.sessionTones, false, "Settings shows the switch, off")
        let older = try JSONDecoder().decode(API.Prefs.self, from: Data("{}".utf8))
        XCTAssertNil(older.sessionTones, "an older Mac has no such setting: no switch is shown")
    }

    func testASessionNamesItsToneOnceItHasOne() throws {
        let status = try JSONDecoder().decode(API.Status.self, from: Data(#"""
        {"connected": true, "sessions": [{"name": "docs", "working": false, "waiting": false, "harness": "codex", "tone": {"index": 2, "name": "double"}},
                                         {"name": "billing", "working": true, "waiting": false, "tone": null}]}
        """#.utf8))
        XCTAssertEqual(TonesCopy.label(status.sessions[0]), "tone: double")
        XCTAssertNil(TonesCopy.label(status.sessions[1]), "no tone yet, or the setting is off: the Mac sends none")
        XCTAssertEqual(status.sessions[0].tone, API.SessionTone(index: 2, name: "double"))
    }
}
