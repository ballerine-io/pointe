import XCTest
@testable import PointeUI

/// Reading mode (docs/features/reading-mode.md): Pointe writes, the owner reads. Each device keeps its own choice, tells
/// the Mac when it calls, and keeps what the Mac says when the owner changed it by voice. The words are the page's.
final class ReadingTests: XCTestCase {
    private func status(_ json: String) throws -> API.Status {
        try JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    private func defaults() -> UserDefaults {
        let name = "reading-tests-\(UUID().uuidString)"
        let d = UserDefaults(suiteName: name)!
        d.removePersistentDomain(forName: name)
        return d
    }

    func testTheMacsStatusDecodes() throws {
        let s = try status(#"""
        {"connected": true, "sessions": [], "reading": {"on": true, "held": "drive", "read_through": 7},
         "talk": [{"id": 7, "who": "assistant", "text": "Done.", "unread": false},
                  {"id": 8, "who": "assistant", "text": "Billing finished.", "unread": true}]}
        """#)
        XCTAssertEqual(s.reading, API.ReadingStatus(on: true, held: "drive", read_through: 7))
        XCTAssertEqual(s.talk?.map(\.unread), [false, true])
    }

    func testAnOlderMacWithoutReadingModeDecodesAsNil() throws {
        let s = try status(#"{"connected": true, "sessions": [], "talk": [{"id": 1, "who": "assistant", "text": "Hi."}]}"#)
        XCTAssertNil(s.reading)
        XCTAssertNil(s.talk?.first?.unread)
    }

    func testTheCallsStateShowsWhileACallIsUpAndTheDevicesOwnChoiceOtherwise() throws {
        let callOn = try status(#"{"connected": true, "sessions": [], "reading": {"on": true, "held": null, "read_through": -1}}"#)
        let callOff = try status(#"{"connected": true, "sessions": [], "reading": {"on": false, "held": null, "read_through": -1}}"#)
        let noCall = try status(#"{"connected": false, "sessions": [], "reading": {"on": false, "held": null, "read_through": -1}}"#)
        XCTAssertTrue(ReadingChoice.on(status: callOn, stored: false), "a call is up: the call's state")
        XCTAssertFalse(ReadingChoice.on(status: callOff, stored: true))
        XCTAssertTrue(ReadingChoice.on(status: noCall, stored: true), "no call: this device's own choice")
        XCTAssertFalse(ReadingChoice.on(status: nil, stored: false))
    }

    func testDriveModeHoldsIt() throws {
        let held = try status(#"{"connected": true, "sessions": [], "reading": {"on": true, "held": "drive", "read_through": -1}}"#)
        XCTAssertTrue(ReadingChoice.on(status: held, stored: false))
        XCTAssertFalse(ReadingChoice.inEffect(status: held, stored: false), "on the road Pointe talks: no unread marks")
    }

    func testTheChoiceIsKeptOnThisDevice() {
        let d = defaults()
        XCTAssertFalse(ReadingChoice.stored(d), "off until chosen")
        ReadingChoice.store(true, d)
        XCTAssertTrue(ReadingChoice.stored(d))
        XCTAssertTrue(d.bool(forKey: "reading"))
        ReadingChoice.store(false, d)
        XCTAssertFalse(ReadingChoice.stored(d))
    }

    func testTheCallsAddressCarriesTheChoice() throws {
        let phone = try XCTUnwrap(URL(string: "wss://mac.example:7443/voice/phone"))
        XCTAssertEqual(ReadingChoice.callURL(phone, on: true).absoluteString, "wss://mac.example:7443/voice/phone?reading=1")
        XCTAssertEqual(ReadingChoice.callURL(phone, on: false), phone)
    }

    func testTheMacsMessageIsKept() {
        XCTAssertEqual(ReadingChoice.message(["type": "reading", "on": true]), true)
        XCTAssertEqual(ReadingChoice.message(["type": "reading", "on": false]), false)
        XCTAssertNil(ReadingChoice.message(["type": "reading", "on": "yes"]))
        XCTAssertNil(ReadingChoice.message(["type": "ptt", "open": true]))
    }

    func testTheWordsAreThePages() {
        XCTAssertEqual(ReadingCopy.button, "Read")
        XCTAssertEqual(ReadingCopy.buttonOn, "Reading")
        XCTAssertEqual(ReadingCopy.title, "Reading mode: Pointe writes, you read.")
        XCTAssertEqual(ReadingCopy.body, "Nothing is spoken. Talk or type as usual. A reply stays unread until you tap it, talk or type.")
        XCTAssertEqual(ReadingCopy.back, "Talk again")
        XCTAssertEqual(ReadingCopy.unread, "Unread")
        XCTAssertEqual(ReadingCopy.read, "Read")
        XCTAssertEqual(ReadingCopy.markRead, "Mark all read")
        XCTAssertEqual(ReadingCopy.held, "Drive mode holds reading mode: Pointe talks while you drive.")
        XCTAssertEqual(ReadingCopy.failed, "Reading mode did not change: the voice is not reachable.")
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
final class ReadingDemoTests: XCTestCase {
    func testTheReadingAndHeldScreensDecode() throws {
        let reading = try XCTUnwrap(Demo.make(.reading, english: true))
        XCTAssertTrue(ReadingChoice.inEffect(status: reading.status, stored: false))
        XCTAssertEqual(reading.status.talk?.filter { $0.unread == true }.count, 1)
        XCTAssertTrue(reading.status.talk?.contains { $0.text.contains("\n") } == true, "a typed line with its line break")
        let held = try XCTUnwrap(Demo.make(.held, english: true))
        XCTAssertEqual(held.status.mode, "session")
        XCTAssertEqual(HeldCopy.badge(held.status.held), "2 updates from other sessions")
        let waiting = held.status.sessions.filter { $0.waiting && $0.canApprove }
        XCTAssertEqual(waiting.map(\.name), ["river-lantern"], "another session's request stays on its card in session mode")
    }
}
