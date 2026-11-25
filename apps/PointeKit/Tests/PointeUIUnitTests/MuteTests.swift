import XCTest
@testable import PointeUI

/// Mute (docs/features/mute.md): one toggle beside the status line. Muted, Pointe writes where it would have spoken, and
/// the line says "Writing…". Each device keeps its own choice, tells the Mac when it calls, and keeps what the Mac says
/// when the owner changed it by voice. The words are the page's.
final class MuteTests: XCTestCase {
    private func status(_ json: String) throws -> API.Status {
        try JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    private func defaults() -> UserDefaults {
        let name = "mute-tests-\(UUID().uuidString)"
        let d = UserDefaults(suiteName: name)!
        d.removePersistentDomain(forName: name)
        return d
    }

    func testTheMacsStatusDecodes() throws {
        let s = try status(#"""
        {"connected": true, "sessions": [], "reading": {"on": true, "held": "drive", "read_through": 7, "writing": true},
         "talk": [{"id": 7, "who": "assistant", "text": "Done.", "unread": false}]}
        """#)
        XCTAssertEqual(s.reading, API.ReadingStatus(on: true, held: "drive", read_through: 7, writing: true))
    }

    func testAnOlderMacDecodes() throws {
        let none = try status(#"{"connected": true, "sessions": [], "talk": [{"id": 1, "who": "assistant", "text": "Hi."}]}"#)
        XCTAssertNil(none.reading, "a Mac from before reading mode: no mute button")
        let reading = try status(#"{"connected": true, "sessions": [], "reading": {"on": true, "held": null, "read_through": -1}}"#)
        XCTAssertNil(reading.reading?.writing, "a Mac with reading mode and no Writing… state")
        XCTAssertFalse(MuteChoice.writing(status: reading, stored: true))
    }

    func testTheCallsStateShowsWhileACallIsUpAndTheDevicesOwnChoiceOtherwise() throws {
        let callOn = try status(#"{"connected": true, "sessions": [], "reading": {"on": true, "held": null, "read_through": -1}}"#)
        let callOff = try status(#"{"connected": true, "sessions": [], "reading": {"on": false, "held": null, "read_through": -1}}"#)
        let noCall = try status(#"{"connected": false, "sessions": [], "reading": {"on": false, "held": null, "read_through": -1}}"#)
        XCTAssertTrue(MuteChoice.on(status: callOn, stored: false), "a call is up: the call's state")
        XCTAssertFalse(MuteChoice.on(status: callOff, stored: true))
        XCTAssertTrue(MuteChoice.on(status: noCall, stored: true), "no call: this device's own choice")
        XCTAssertFalse(MuteChoice.on(status: nil, stored: false))
    }

    func testDriveModeHoldsIt() throws {
        let held = try status(#"{"connected": true, "sessions": [], "reading": {"on": true, "held": "drive", "read_through": -1, "writing": true}}"#)
        XCTAssertTrue(MuteChoice.on(status: held, stored: false))
        XCTAssertFalse(MuteChoice.inEffect(status: held, stored: false), "on the road Pointe talks")
        XCTAssertFalse(MuteChoice.writing(status: held, stored: false))
    }

    func testWritingIsTheMacsWordWhileMuted() throws {
        let writing = try status(#"{"connected": true, "sessions": [], "reading": {"on": true, "held": null, "read_through": -1, "writing": true}}"#)
        let quiet = try status(#"{"connected": true, "sessions": [], "reading": {"on": true, "held": null, "read_through": -1, "writing": false}}"#)
        let unmuted = try status(#"{"connected": true, "sessions": [], "reading": {"on": false, "held": null, "read_through": -1, "writing": true}}"#)
        XCTAssertTrue(MuteChoice.writing(status: writing, stored: false))
        XCTAssertFalse(MuteChoice.writing(status: quiet, stored: true))
        XCTAssertFalse(MuteChoice.writing(status: unmuted, stored: true))
        XCTAssertFalse(MuteChoice.writing(status: nil, stored: true), "no call: nothing is being written")
    }

    @MainActor
    func testTheStatusLineSaysSpeakingAndMutedItSaysWriting() throws {
        let call = Call(pairing: Pairing(host: "studio.example.ts.net", port: 7443, fingerprint: String(repeating: "a", count: 64),
                                         key: String(repeating: "k", count: 32)))
        let writing = try status(#"{"connected": true, "sessions": [], "reading": {"on": true, "held": null, "read_through": -1, "writing": true}}"#)
        let quiet = try status(#"{"connected": true, "sessions": [], "reading": {"on": true, "held": null, "read_through": -1, "writing": false}}"#)
        func title(_ status: API.Status?, speaking: Bool = false, muted: Bool = false) -> String {
            CallTitle.line(phase: .live, reach: .ok, status: status, call: call, macName: "studio", dumping: false, talking: false,
                           speaking: speaking, muted: muted)
        }
        XCTAssertEqual(title(nil, speaking: true), "Speaking…")
        XCTAssertEqual(title(writing), "Writing…")
        XCTAssertEqual(title(quiet), "Listening")
        XCTAssertEqual(title(writing, speaking: true), "Speaking…", "sound that still plays is said first")
        XCTAssertEqual(title(writing, muted: true), "Mic off", "the microphone's own state comes first, as before")
    }

    func testTheButtonSaysWhatATapDoes() {
        XCTAssertEqual(MuteButton.label(on: false), "Mute Pointe")
        XCTAssertEqual(MuteButton.label(on: true), "Unmute Pointe")
        // The icon is the state now, the label is what a tap does: a slash while the voice is on read as "already muted".
        XCTAssertEqual(MuteButton.symbol(on: false), "speaker.wave.2")
        XCTAssertEqual(MuteButton.symbol(on: true), "speaker.slash.fill")
        XCTAssertEqual(MuteButton.hint(on: true, held: true), MuteCopy.held)
        XCTAssertNil(MuteButton.hint(on: true, held: false))
    }

    func testTheChoiceIsKeptOnThisDevice() {
        let d = defaults()
        XCTAssertFalse(MuteChoice.stored(d), "off until chosen")
        MuteChoice.store(true, d)
        XCTAssertTrue(MuteChoice.stored(d))
        XCTAssertTrue(d.bool(forKey: "reading"), "the key reading mode kept: a device that chose it stays muted")
        MuteChoice.store(false, d)
        XCTAssertFalse(MuteChoice.stored(d))
    }

    func testTheCallsAddressCarriesTheChoice() throws {
        let phone = try XCTUnwrap(URL(string: "wss://mac.example:7443/voice/phone"))
        XCTAssertEqual(MuteChoice.callURL(phone, on: true).absoluteString, "wss://mac.example:7443/voice/phone?reading=1")
        XCTAssertEqual(MuteChoice.callURL(phone, on: false), phone)
    }

    func testTheMacsMessageIsKept() {
        XCTAssertEqual(MuteChoice.message(["type": "reading", "on": true]), true)
        XCTAssertEqual(MuteChoice.message(["type": "reading", "on": false]), false)
        XCTAssertNil(MuteChoice.message(["type": "reading", "on": "yes"]))
        XCTAssertNil(MuteChoice.message(["type": "ptt", "open": true]))
    }

    func testTheWordsAreThePages() {
        XCTAssertEqual(MuteCopy.speaking, "Speaking…")
        XCTAssertEqual(MuteCopy.writing, "Writing…")
        XCTAssertEqual(MuteCopy.mute, "Mute Pointe")
        XCTAssertEqual(MuteCopy.unmute, "Unmute Pointe")
        XCTAssertEqual(MuteCopy.held, "Drive mode holds mute: Pointe talks while you drive.")
        XCTAssertEqual(MuteCopy.failed, "Mute did not change: the voice is not reachable.")
    }

    func testSettingsHasNoReadSwitch() {
        let names = Mirror(reflecting: CallSettingsModel()).children.compactMap(\.label)
        XCTAssertFalse(names.contains("reading"), "the Read setting is gone: mute is the button beside the status line")
    }

    // MARK: held news (session mode)

    func testHeldNewsDecodesAndShowsOnlyWhenThereIsSome() throws {
        let s = try status(#"""
        {"connected": true, "sessions": [], "mode": "session",
         "held": {"count": 2, "line": "2 updates from other sessions", "approvals": 1,
                  "items": [{"session": "beta", "kind": "report", "line": "all 12 tests pass", "at": 1.0},
                            {"session": "gamma", "kind": "approval", "line": "needs your approval", "at": 2.0}]}}
        """#)
        XCTAssertEqual(s.held?.count, 2)
        XCTAssertEqual(HeldCopy.badge(s.held), "2 updates from other sessions")
        XCTAssertEqual(s.held?.items?.map(HeldCopy.item), ["beta · all 12 tests pass", "gamma · needs your approval"])
        let none = try status(#"{"connected": true, "sessions": [], "held": {"count": 0, "line": "", "approvals": 0, "items": []}}"#)
        XCTAssertNil(HeldCopy.badge(none.held))
        XCTAssertNil(HeldCopy.badge(nil), "an older Mac")
        XCTAssertEqual(HeldCopy.tell, "Tell me")
    }
}

/// The screens the pictures and the Mac smoke are taken from decode, and show what they are for.
final class MuteDemoTests: XCTestCase {
    func testTheWritingAndHeldScreensDecode() throws {
        let writing = try XCTUnwrap(Demo.make(.writing, english: true))
        XCTAssertTrue(MuteChoice.inEffect(status: writing.status, stored: false))
        XCTAssertTrue(MuteChoice.writing(status: writing.status, stored: false))
        XCTAssertTrue(writing.status.talk?.contains { $0.text.contains("\n") } == true, "a typed line with its line break")
        let speaking = try XCTUnwrap(Demo.make(.speaking, english: true))
        XCTAssertNotNil(speaking.status.reading, "the Speaking… screen has the mute button")
        XCTAssertFalse(MuteChoice.on(status: speaking.status, stored: false))
        let held = try XCTUnwrap(Demo.make(.held, english: true))
        XCTAssertEqual(held.status.mode, "session")
        XCTAssertEqual(HeldCopy.badge(held.status.held), "2 updates from other sessions")
        let waiting = held.status.sessions.filter { $0.waiting && $0.canApprove }
        XCTAssertEqual(waiting.map(\.name), ["river-lantern"], "another session's request stays on its card in session mode")
    }
}
