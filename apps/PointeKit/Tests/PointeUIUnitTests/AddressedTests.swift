import XCTest
@testable import PointeUI

/// Addressed speech (docs/features/addressed-speech.md): "Only when I say Pointe", the third microphone setting. The
/// Mac decides what is addressed; the apps show the setting, and the state line says how to talk.
@MainActor
final class AddressedTests: XCTestCase {
    private func status(_ json: String) -> API.Status {
        try! JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    func testTheStateLineSaysHowToTalkWhereItSaidListening() {
        let on = status(#"{"connected": true, "sessions": [], "ptt": {"mode": "addressed", "open": false}, "addressed": {"on": true, "open": false, "dropped": 2}}"#)
        XCTAssertEqual(AddressedCopy.line(on), "Say “Pointe” to talk")
        XCTAssertEqual(on.ptt?.mode, AddressedCopy.mode)
        XCTAssertEqual(on.addressed?.dropped, 2)
    }

    func testAfterTheNameAloneTheLineSaysListening() {
        let open = status(#"{"connected": true, "sessions": [], "addressed": {"on": true, "open": true}}"#)
        XCTAssertEqual(AddressedCopy.line(open), "Listening")
    }

    func testAlwaysOnAndAnOlderMacKeepListening() {
        XCTAssertNil(AddressedCopy.line(status(#"{"connected": true, "sessions": [], "addressed": null}"#)))
        XCTAssertNil(AddressedCopy.line(status(#"{"connected": true, "sessions": []}"#)), "an older Mac sends no such field")
        XCTAssertNil(AddressedCopy.line(nil))
    }

    func testTheModeIsNotPushToTalkSoTheMicrophoneStaysOpen() {
        var gate = TalkGate()
        gate.mode = AddressedCopy.mode
        XCTAssertFalse(gate.ptt, "no press is needed: the Mac hears everything and acts on what is addressed")
    }

    func testTheDemoShowsTheMode() throws {
        let demo = try XCTUnwrap(Demo.make(.addressed))
        XCTAssertEqual(AddressedCopy.line(demo.status), AddressedCopy.idle)
        XCTAssertEqual(demo.status.ptt?.mode, "addressed")
    }
}
