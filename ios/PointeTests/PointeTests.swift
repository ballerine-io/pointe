import XCTest
@testable import Pointe

final class PairingTests: XCTestCase {
    let fp = String(repeating: "ab", count: 32)
    let key = String(repeating: "k", count: 43)

    func testAPairingLinkFromPointePairIsRead() {
        let p = Pairing(link: "pointe://pair?v=1&host=mac.tail1234.ts.net&port=7443&fp=\(fp)&key=\(key)")
        XCTAssertEqual(p, Pairing(host: "mac.tail1234.ts.net", port: 7443, fingerprint: fp, key: key))
        XCTAssertEqual(p?.callURL.absoluteString, "wss://mac.tail1234.ts.net:7443/voice/phone")
    }

    func testAnythingElseIsRefused() {
        for link in ["https://evil.example/pair?v=1&host=a&port=1&fp=\(fp)&key=\(key)",  // not ours
                     "pointe://pair?v=2&host=a&port=7443&fp=\(fp)&key=\(key)",           // a version this app does not know
                     "pointe://pair?v=1&host=a&port=7443&fp=abc&key=\(key)",             // no real fingerprint
                     "pointe://pair?v=1&host=a/b&port=7443&fp=\(fp)&key=\(key)",         // a path smuggled into the host
                     "pointe://pair?v=1&host=a&port=99999&fp=\(fp)&key=\(key)",
                     "pointe://pair?v=1&host=a&port=7443&fp=\(fp)&key=short", ""] {
            XCTAssertNil(Pairing(link: link), link)
        }
    }
}

final class WireTests: XCTestCase {
    func testPCMRoundTrip() {
        let samples: [Float] = [0, 0.5, -0.5, 1, -1]
        let back = Wire.floats(Wire.pcm16(samples))
        for (a, b) in zip(samples, back) { XCTAssertEqual(a, b, accuracy: 0.001) }
        XCTAssertEqual(Wire.pcm16(samples).count, 10)  // 16-bit mono
    }

    func testResampleKeepsDuration() {
        let second = [Float](repeating: 0.1, count: 48000)
        XCTAssertEqual(Wire.resample(second, from: 48000, to: Wire.upRate).count, 16000)
        XCTAssertEqual(Wire.resample(second, from: 48000, to: 48000).count, 48000)
    }
}

final class MeetingTests: XCTestCase {
    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try JSONDecoder().decode(type, from: Data(json.utf8))
    }

    func testAnOlderDaemonWithoutMeetingFieldsStillDecodes() throws {
        let status = try decode(API.Status.self, #"{"connected": true, "mode": "orchestrator", "sessions": [], "talk": []}"#)
        XCTAssertNil(status.meeting)
        XCTAssertNil(status.notes)
    }

    func testAnEndedMeetingHasNoSinceAndIsEnded() throws {
        let status = try decode(API.Status.self, #"{"connected": true, "sessions": [], "meeting": {"on": false, "ended": true,"#
                                + #""result": {"summary": "s", "action_items": [{"what": "w", "owner": null, "due": null}]}}}"#)
        XCTAssertEqual(status.meeting?.isEnded, true)
        XCTAssertEqual(status.meeting?.isOn, false)
        XCTAssertNil(status.meeting?.since)  // why the app keys the end sheet by the since it saw while the meeting was on
    }

    func testUnknownFieldsAndMissingOnesAreTolerated() throws {
        let note = try decode(API.Note.self, #"{"id": 3, "kind": "question", "text": "q", "brand_new": 1}"#)
        XCTAssertEqual(note.kind, "question")
        let prefs = try decode(API.Prefs.self, #"{"meeting.auto_lookups": true, "meeting.default_mode": 7}"#)
        XCTAssertTrue(prefs.autoLookups)
        XCTAssertEqual(prefs.defaultMode, "listening")  // a wrong type falls back, not a failed decode
    }

    func testTheMacsReasonsBecomeSentences() {
        XCTAssertEqual(CallView.sentence("end the meeting first"), "End the meeting first.")
        XCTAssertEqual(CallView.sentence("No call is up."), "No call is up.")  // no double full stop
        XCTAssertEqual(CallView.sentence(""), "")
    }

    func testMarkdownHasTheTranscriptOnlyWhenGiven() throws {
        let result = try decode(API.MeetingResult.self, #"{"summary": "We agreed.", "decisions": ["Ship"], "open_questions": ["Q?"]}"#)
        let items = [API.ActionItem(what: "Write the note", owner: "Dana", due: "")]
        let notes = [try decode(API.Note.self, #"{"id": 1, "kind": "answer", "text": "30 seconds", "state": "open"}"#),
                     try decode(API.Note.self, #"{"id": 2, "kind": "answer", "text": "hidden", "state": "dismissed"}"#)]
        let turn = try decode(API.TranscriptTurn.self, #"{"id": 1, "who": "Dana", "speaker": "2", "text": "Hello"}"#)
        let without = MeetingCopy.markdown(result: result, items: items, notes: notes, transcript: [])
        XCTAssertTrue(without.contains("- Write the note (owner: Dana)\n"), "an empty due is left out")
        XCTAssertTrue(without.contains("## Answers found\n- 30 seconds"))
        XCTAssertFalse(without.contains("hidden"))
        XCTAssertFalse(without.contains("## Transcript"))
        let with = MeetingCopy.markdown(result: result, items: items, notes: notes, transcript: [turn])
        XCTAssertTrue(with.contains("## Transcript\n- Dana: Hello"))
    }
}
