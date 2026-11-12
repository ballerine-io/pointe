import XCTest
@testable import Pointe

/// Drive & walk mode on the phone: the status contract, the copy (word for word the page's), what the card says instead
/// of buttons, and when the mode is suggested (never entered by itself).
final class DriveTests: XCTestCase {
    private func status(_ json: String) throws -> API.Status {
        try JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    private let request = #"""
    {"connected": true, "sessions": [{"name": "lantern", "working": false, "waiting": true, "request": "Bash: x",
      "request_id": "r1", "voice_can_approve": true}], "drive": {"on": true, "since": 1700000000, "how": "voice",
      "pending": [{"session": "lantern", "request_id": "r1", "voice": VOICE}]}VOICELOCK}
    """#

    private func driving(voice: Bool, canApprove: Bool = true, enrolled: Bool = false) throws -> API.Status {
        var json = request.replacingOccurrences(of: "VOICE", with: voice ? "true" : "false", options: [], range: request.range(of: "VOICE}"))
        json = json.replacingOccurrences(of: "VOICELOCK", with: enrolled ? #", "voice_lock": {"level": "off", "enrolled": true}"# : "")
        if !canApprove { json = json.replacingOccurrences(of: #""voice_can_approve": true"#, with: #""voice_can_approve": false"#) }
        return try status(json)
    }

    func testAnOlderMacWithoutDriveModeHidesIt() throws {
        let s = try status(#"{"connected": true, "sessions": []}"#)
        XCTAssertNil(s.drive)
        XCTAssertFalse(s.driving)
    }

    func testTheContractDecodes() throws {
        let s = try driving(voice: false)
        XCTAssertTrue(s.driving)
        XCTAssertEqual(s.drive?.how, "voice")
        XCTAssertEqual(s.drive?.pending, [API.DrivePending(session: "lantern", request_id: "r1", voice: false)])
    }

    func testTheCardSaysHowARequestMayBeAnswered() throws {
        var s = try driving(voice: true)
        XCTAssertEqual(DriveCopy.hint(for: s.sessions[0], status: s), "Say yes or no.")
        s = try driving(voice: true, enrolled: true)
        XCTAssertEqual(DriveCopy.hint(for: s.sessions[0], status: s), "Say yes or no, in a full sentence.")
        s = try driving(voice: false)
        XCTAssertEqual(DriveCopy.hint(for: s.sessions[0], status: s), "Not for the road: it waits until you stop. Say no to deny it.")
        s = try driving(voice: false, canApprove: false)
        XCTAssertEqual(DriveCopy.hint(for: s.sessions[0], status: s),
                       "Can\u{2019}t be read out: it waits until you stop. Say no to deny it.")
    }

    func testAnUnknownRequestIsNeverSaidToBeAnswerableByVoice() throws {
        let s = try status(#"""
        {"connected": true, "sessions": [{"name": "lantern", "working": false, "waiting": true, "request_id": "r9",
          "voice_can_approve": true}], "drive": {"on": true, "pending": []}}
        """#)
        XCTAssertEqual(DriveCopy.hint(for: s.sessions[0], status: s), DriveCopy.road)
    }

    func testTheBigLine() throws {
        XCTAssertEqual(DriveCopy.line(status: try driving(voice: false), speaking: true, hearing: false), "lantern needs you")
        let quiet = try status(#"{"connected": true, "sessions": [{"name": "a", "working": true, "waiting": false}], "drive": {"on": true}}"#)
        XCTAssertEqual(DriveCopy.line(status: quiet, speaking: true, hearing: false), "Speaking")
        XCTAssertEqual(DriveCopy.line(status: quiet, speaking: false, hearing: true), "Listening")
        XCTAssertEqual(DriveCopy.line(status: quiet, speaking: false, hearing: false), "1 working")
        XCTAssertEqual(DriveNowPlaying.info(status: try driving(voice: false))["title"] as? String, "Pointe · lantern needs you")
    }

    func testTheCopyMatchesThePage() throws {
        let page = try String(contentsOf: URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("../../ui.html").standardizedFileURL, encoding: .utf8)
        for line in [DriveCopy.voice, DriveCopy.voiceStrong, DriveCopy.road, DriveCopy.hint, DriveCopy.title, DriveCopy.stop, DriveCopy.unreadable] {
            XCTAssertTrue(page.contains(line), line)
        }
    }

    // MARK: the suggestion

    func testCarPlaySuggestsOnceUntilTheTripEnds() {
        var s = DriveSuggester()
        let now = Date()
        XCTAssertFalse(s.suggests(enabled: true, live: true, driving: false, meeting: false, now: now))
        s.route(inCar: true)
        XCTAssertTrue(s.suggests(enabled: true, live: true, driving: false, meeting: false, now: now))
        XCTAssertFalse(s.suggests(enabled: false, live: true, driving: false, meeting: false, now: now), "the setting is off")
        XCTAssertFalse(s.suggests(enabled: true, live: false, driving: false, meeting: false, now: now), "no call")
        XCTAssertFalse(s.suggests(enabled: true, live: true, driving: true, meeting: false, now: now), "already on")
        XCTAssertFalse(s.suggests(enabled: true, live: true, driving: false, meeting: true, now: now), "a meeting")
        s.dismiss()
        XCTAssertFalse(s.suggests(enabled: true, live: true, driving: false, meeting: false, now: now))
        s.route(inCar: false)
        s.route(inCar: true)
        XCTAssertTrue(s.suggests(enabled: true, live: true, driving: false, meeting: false, now: now), "a new trip")
    }

    func testAMinuteOfDrivingSuggests() {
        var s = DriveSuggester()
        let t0 = Date()
        s.motion(automotive: true, at: t0)
        XCTAssertFalse(s.suggests(enabled: true, live: true, driving: false, meeting: false, now: t0.addingTimeInterval(30)))
        s.motion(automotive: true, at: t0.addingTimeInterval(30))
        XCTAssertTrue(s.suggests(enabled: true, live: true, driving: false, meeting: false, now: t0.addingTimeInterval(61)))
        s.motion(automotive: false, at: t0.addingTimeInterval(62))
        XCTAssertFalse(s.suggests(enabled: true, live: true, driving: false, meeting: false, now: t0.addingTimeInterval(63)))
    }
}
