import XCTest
@testable import PointeUI

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

    /// A host with a colon makes no URL: one such link would crash the app at every launch, and the Keychain keeps it.
    func testAHostThatMakesNoAddressIsRefused() throws {
        for host in ["a:b", "::1", "a:", "1.2.3.4:5"] {
            XCTAssertNil(Pairing(link: "pointe://pair?v=1&host=\(host)&port=7443&fp=\(fp)&key=\(key)"), host)
            XCTAssertNil(PairingLink("pointe://pair?v=2&host=\(host)&port=7443&fp=\(fp)&code=ABCD-EFGH"), host)
            let stored = try JSONSerialization.data(withJSONObject: ["host": host, "port": 7443, "fingerprint": fp, "key": key] as [String: Any])
            XCTAssertNil(try? JSONDecoder().decode(Pairing.self, from: stored), "a stored pairing to \(host) is not used")
        }
        let good = try JSONEncoder().encode(Pairing(host: "mac.example", port: 7443, fingerprint: fp, key: key))
        XCTAssertEqual(try JSONDecoder().decode(Pairing.self, from: good).base.absoluteString, "https://mac.example:7443")
    }
}

/// The page's QR (Settings → Phone): a one-time code the app trades for the key over the pinned listener.
final class PairingInviteTests: XCTestCase {
    let fp = String(repeating: "ab", count: 32)

    func testACodeLinkFromThePageIsRead() {
        let i = PairingInvite(link: "pointe://pair?v=2&host=pointe.example.internal&port=7443&fp=\(fp)&code=TKMC-PNM7")
        XCTAssertEqual(i, PairingInvite(host: "pointe.example.internal", port: 7443, fingerprint: fp, code: "TKMC-PNM7"))
        XCTAssertEqual(i?.pairURL.absoluteString, "https://pointe.example.internal:7443/voice/phone/pair")
    }

    func testEitherKindOfLinkIsRecognisedAndNothingElse() {
        let key = String(repeating: "k", count: 43)
        guard case .ready? = PairingLink("pointe://pair?v=1&host=a.b&port=7443&fp=\(fp)&key=\(key)") else { return XCTFail("v1") }
        guard case .invite? = PairingLink("pointe://pair?v=2&host=a.b&port=7443&fp=\(fp)&code=ABCD-EFGH") else { return XCTFail("v2") }
        for link in ["pointe://pair?v=2&host=a&port=7443&fp=\(fp)&key=\(key)",         // a key, no code
                     "pointe://pair?v=1&host=a&port=7443&fp=\(fp)&code=ABCD-EFGH",       // a code under the old version
                     "pointe://pair?v=2&host=a/b&port=7443&fp=\(fp)&code=ABCD-EFGH",     // a path smuggled into the host
                     "pointe://pair?v=2&host=a&port=7443&fp=abc&code=ABCD-EFGH",          // no real fingerprint
                     "pointe://pair?v=2&host=a&port=7443&fp=\(fp)&code=AB",              // not a code
                     "pointe://hub?v=2&host=a&port=7443&fp=\(fp)&code=ABCD-EFGH",        // a machine invite
                     "https://evil.example/pair?v=2&host=a&port=7443&fp=\(fp)&code=ABCD-EFGH", ""] {
            XCTAssertNil(PairingLink(link), link)
        }
    }

    func testTheTradeSendsTheCodeAndTheDeviceAndNoSecret() throws {
        let i = PairingInvite(host: "mac.example", port: 7443, fingerprint: fp, code: "ABCD-EFGH")
        let r = i.request(device: "Mira's iPhone", id: "dev-1")
        XCTAssertEqual(r.httpMethod, "POST")
        XCTAssertNil(r.value(forHTTPHeaderField: "Authorization"))
        let body = try JSONSerialization.jsonObject(with: r.httpBody ?? Data()) as? [String: String]
        XCTAssertEqual(body, ["code": "ABCD-EFGH", "device": "Mira's iPhone", "id": "dev-1"])
    }

    func testTheDeviceNameTravelsAsASCII() {
        XCTAssertEqual(API.header(for: "Mira’s iPhone"), "Mira%E2%80%99s%20iPhone")
        XCTAssertTrue(API.header(for: "Mira’s iPhone").allSatisfy(\.isASCII))
    }

    func testARefusalSaysWhatToDoNext() {
        XCTAssertTrue(PairingInvite.problem(status: 403, text: "invite expired").contains("Connect your phone"))
        XCTAssertTrue(PairingInvite.problem(status: 403, text: "wrong code").contains("expired or was already used"))
        XCTAssertTrue(PairingInvite.problem(status: 429, text: "too many attempts: wait a minute").contains("Wait a minute"))
        XCTAssertTrue(PairingInvite.unreachable(host: "mac.example").contains("Can't reach your Mac at mac.example"))
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

    /// The phone's own keep-alive, word for word as tests/test_phone.py feeds it to the Mac: a pong for a ping already
    /// answered, so a Mac before protocol 4 counts it and measures no round trip from it.
    func testTheKeepAliveIsAPongForTheNewestPingAlreadyAnswered() {
        XCTAssertEqual(Call.alive(answered: 3), #"{"alive":true,"id":3,"type":"pong"}"#)
        XCTAssertEqual(Call.alive(answered: 0), #"{"alive":true,"id":0,"type":"pong"}"#)  // before the first ping
        XCTAssertLessThan(Call.aliveEvery, .seconds(6), "well inside the Mac's 12 s, with one lost on the way")
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

    func testTheEndSheetShowsWhatTheVoiceDidWithTheActionItems() throws {
        let asked = try decode(API.Meeting.self, #"{"on": false, "ended": true, "result": {"summary": "S"}, "send_pending": {"session": "billing", "line": "Send 2 action items to billing: A; B. Send them?", "expires_in": 50}, "sent_to": null}"#)
        XCTAssertEqual(MeetingCopy.sendLine(sent: nil, pending: asked.send_pending, sentTo: asked.sent_to),
                       "Pointe asked: “Send 2 action items to billing: A; B. Send them?” Say yes, or send it here.")
        let sent = try decode(API.Meeting.self, #"{"on": false, "ended": true, "result": {"summary": "S"}, "sent_to": "billing"}"#)
        XCTAssertEqual(MeetingCopy.sendLine(sent: nil, pending: sent.send_pending, sentTo: sent.sent_to), "Asked billing to take them.")
        XCTAssertEqual(MeetingCopy.sendLine(sent: "Asked docs to take them.", pending: nil, sentTo: "billing"), "Asked docs to take them.")
        let older = try decode(API.Meeting.self, #"{"on": false, "ended": true, "result": {"summary": "S"}}"#)  // an older Mac
        XCTAssertNil(MeetingCopy.sendLine(sent: nil, pending: older.send_pending, sentTo: older.sent_to))
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

/// The notes feed against a stand-in fetch: what it asks the Mac for, and the order answers land in.
@MainActor
final class MeetingFeedTests: XCTestCase {
    private func status(version: Int, id: String = "m1", since: Double = 1000) -> API.Status {
        try! JSONDecoder().decode(API.Status.self, from: Data("""
            {"connected": true, "sessions": [], "notes": {"version": \(version)}, "meeting": {"on": true, "id": "\(id)", "since": \(since)}}
            """.utf8))
    }

    private func note(_ id: Int, _ state: String, meeting: String? = "m1", at: Double = 1010) -> API.Note {
        API.Note(id: id, kind: "speaker", at: at, updated: nil, text: "Speaker 2 may be Dana", meta: nil, speakers: nil,
                 session: nil, state: state, meeting: meeting)
    }

    func testAnOlderAnswerArrivingLastDoesNotUndoANewerOne() async {
        let feed = MeetingFeed()
        await feed.sync(status(version: 1)) { _, _ in API.NotesPage(version: 1, notes: [self.note(7, "open")]) }
        // One poll asks while the suggestion is open, and is answered only after a later poll saw it accepted.
        var asked = false
        let (gate, open) = AsyncStream<Void>.makeStream()
        let late = Task { @MainActor in
            await feed.sync(self.status(version: 2)) { _, _ in
                asked = true
                for await _ in gate { break }
                return API.NotesPage(version: 2, notes: [self.note(7, "open")])
            }
        }
        while !asked { await Task.yield() }
        await feed.sync(status(version: 3)) { _, _ in API.NotesPage(version: 3, notes: [self.note(7, "done")]) }
        open.yield()
        await late.value
        XCTAssertEqual(feed.notes.map(\.state), ["done"], "the accepted suggestion stays accepted")
    }

    func testAfterTheFirstLoadItAsksOnlyForWhatChanged() async {
        let feed = MeetingFeed()
        var asks: [String] = []
        await feed.sync(status(version: 4)) { since, changed in
            asks.append("\(since)/\(changed.map(String.init) ?? "-")")
            return API.NotesPage(version: 4, notes: [self.note(2, "open"), self.note(5, "open")])
        }
        await feed.sync(status(version: 6)) { since, changed in
            asks.append("\(since)/\(changed.map(String.init) ?? "-")")
            return API.NotesPage(version: 6, notes: [self.note(2, "dismissed")])
        }
        XCTAssertEqual(asks, ["0/-", "5/4"])
        XCTAssertEqual(feed.notes.map(\.state), ["dismissed", "open"], "a changed note replaces its copy by id")
    }

    func testOnlyThisMeetingsNotesAreShown() async {
        let feed = MeetingFeed()
        await feed.sync(status(version: 1)) { _, _ in
            API.NotesPage(version: 1, notes: [self.note(1, "open", meeting: "m0"), self.note(2, "open", meeting: nil),
                                              self.note(3, "open")])
        }
        XCTAssertEqual(feed.notes.map(\.id), [3], "not another meeting's, not one written outside a meeting")
        await feed.sync(status(version: 2, id: "m2")) { _, _ in API.NotesPage(version: 2, notes: [self.note(9, "open", meeting: "m2")]) }
        XCTAssertEqual(feed.notes.map(\.id), [9], "a new meeting starts clean, even one started in the same second")
    }

    func testRefusalsReadAsSentences() {
        XCTAssertEqual(CallView.refusal(409, "the meeting is already ending"), "The meeting is already ending: the summary is being written.")
        XCTAssertEqual(CallView.refusal(409, "end the meeting first"), "End the meeting first: it is still on.")
        XCTAssertEqual(CallView.refusal(400, "no session has that name"), "That session is no longer connected. Pick another one.")
        XCTAssertEqual(CallView.refusal(400, "turn_id must be a number"),
                       "Pointe on the Mac did not accept that: turn_id must be a number. Update the app or Pointe on the Mac.")
        XCTAssertEqual(CallView.refusal(409, "A meeting is already on."), "A meeting is already on.")
    }
}
