import XCTest
@testable import Pointe

final class VoiceLockTests: XCTestCase {
    private func status(_ json: String) throws -> API.Status {
        try JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    func testAnOlderDaemonWithoutTheLockHidesIt() throws {
        XCTAssertNil(try status(#"{"connected": true, "sessions": []}"#).voice_lock)
    }

    func testTheFullContractDecodes() throws {
        let s = try status(#"""
        {"connected": true, "sessions": [], "voice_lock": {"level": "commands", "enrolled": true,
         "devices": [{"device": "iPhone · AirPods Pro", "seconds": 30.5, "segments": 6, "enrolled_at": 1700000000.5}],
         "enrolling": {"device": "iPhone", "progress": 0.5, "line": 3, "text": "a line", "seconds": 12.0, "segments": 3,
                       "rejected": 1, "last_reason": "too quiet"},
         "lines": ["1", "2", "3", "4", "5", "6"], "model": "ready", "problem": null,
         "ignored": {"count": 2, "last_at": 1700000100, "recent": [{"at": 1700000090, "secs": 1.8},
                     {"at": 1700000100, "secs": 2.0, "text": "some words"}]},
         "speaker": {"owner": null, "score": null, "at": 1700000100}, "unsure_streak": 3}}
        """#)
        let lock = try XCTUnwrap(s.voice_lock)
        XCTAssertEqual(lock.lockLevel, .commands)
        XCTAssertTrue(lock.isEnrolled)
        XCTAssertEqual(lock.devices?.first?.device, "iPhone · AirPods Pro")
        XCTAssertEqual(lock.enrolling?.progress, 0.5)
        XCTAssertEqual(lock.enrolling?.last_reason, "too quiet")
        XCTAssertEqual(lock.ignored?.count, 2)
        XCTAssertNil(lock.ignored?.recent?.first?.text)
        XCTAssertEqual(lock.ignored?.recent?.last?.text, "some words")
        XCTAssertNil(lock.speaker?.owner)
        XCTAssertEqual(lock.unsure_streak, 3)
    }

    func testAMissingOrUnknownLevelIsOff() throws {
        XCTAssertEqual(try status(#"{"connected": true, "sessions": [], "voice_lock": {}}"#).voice_lock?.lockLevel, .off)
        XCTAssertEqual(try status(#"{"connected": true, "sessions": [], "voice_lock": {"level": "loud"}}"#).voice_lock?.lockLevel, .off)
        XCTAssertFalse(try status(#"{"connected": true, "sessions": [], "voice_lock": {}}"#).voice_lock!.isEnrolled)
    }

    func testOnlyALoweringNeedsTheOwner() {
        let all = VoiceLockLevel.allCases
        XCTAssertEqual(all, [.off, .approvals, .commands, .everything])
        for (i, from) in all.enumerated() {
            for (j, to) in all.enumerated() {
                XCTAssertEqual(VoiceLockLevel.isLowering(from: from, to: to), j < i, "\(from) -> \(to)")
            }
        }
    }

    func testTheDeviceLabel() {
        XCTAssertEqual(VoiceLockCopy.deviceLabel(builtIn: true, route: "iPhone Microphone"), "iPhone")
        XCTAssertEqual(VoiceLockCopy.deviceLabel(builtIn: false, route: "AirPods Pro"), "iPhone · AirPods Pro")
        XCTAssertEqual(VoiceLockCopy.deviceLabel(builtIn: false, route: "  "), "iPhone")
        XCTAssertEqual(VoiceLockCopy.deviceLabel(builtIn: false, route: nil), "iPhone")
    }

    /// The page shows the same words: a change here is a change there.
    func testTheCopy() {
        XCTAssertEqual(VoiceLockLevel.allCases.map(\.label), ["Off", "Approvals", "Commands", "Everything"])
        XCTAssertEqual(VoiceLockLevel.off.help, "Any voice works, as before.")
        XCTAssertEqual(VoiceLockLevel.approvals.help, "A spoken yes counts only in your voice. A no counts from anyone.")
        XCTAssertEqual(VoiceLockLevel.commands.help,
                       "Only your voice reaches Pointe. Other voices are listed as ignored, with their words.")
        XCTAssertEqual(VoiceLockLevel.everything.help, "Only your voice reaches Pointe. Other voices are dropped unseen.")
        XCTAssertEqual(VoiceLockCopy.problem("the model is missing"),
                       "Voice lock can't check voices: the model is missing. Until it can, only a tap approves.")
        XCTAssertEqual(VoiceLockCopy.ignored(2), "2 ignored (not your voice)")
        XCTAssertEqual(VoiceLockCopy.enrolledOn("iPhone"), "Enrolled on: iPhone")
        XCTAssertEqual(VoiceLockCopy.didntCount("too quiet"), "Didn't count: too quiet")
        XCTAssertEqual(VoiceLockCopy.percent(0.424), "42%")
        XCTAssertEqual(VoiceLockCopy.percent(1.3), "100%")
        XCTAssertEqual(VoiceLockCopy.seconds(1.84), "1.8 s")
        XCTAssertEqual(VoiceLockCopy.pushToTalk, "Push to talk is on: hold talk while you read each line.")
    }
}
