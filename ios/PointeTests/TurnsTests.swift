import XCTest
@testable import Pointe

/// Turn taking on the phone: the hold decodes and an older Mac sends none, the setting decodes with Normal as the
/// default, and the words are the page's (tests/test_turn_taking.py holds the same literals).
final class TurnsTests: XCTestCase {
    func testAHoldDecodesAndAnOlderMacSendsNone() throws {
        let held = try JSONDecoder().decode(API.Status.self, from: Data(
            #"{"connected": true, "sessions": [], "hold": {"since": 1700000000.5, "said": "so the checkout keeps timing out"}}"#.utf8))
        XCTAssertEqual(held.hold?.said, "so the checkout keeps timing out")
        XCTAssertEqual(held.hold?.since, 1700000000.5)
        let none = try JSONDecoder().decode(API.Status.self, from: Data(#"{"connected": true, "sessions": [], "hold": null}"#.utf8))
        XCTAssertNil(none.hold)
        XCTAssertNil(try JSONDecoder().decode(API.Status.self, from: Data(#"{"connected": true, "sessions": []}"#.utf8)).hold)
    }

    func testTheSettingDecodesAndDefaultsToNormal() throws {
        let patient = try JSONDecoder().decode(API.Prefs.self, from: Data(#"{"microphone": "always", "turns.patience": "patient"}"#.utf8))
        XCTAssertEqual(patient.patience, "patient")
        let older = try JSONDecoder().decode(API.Prefs.self, from: Data(#"{"microphone": "always"}"#.utf8))
        XCTAssertEqual(older.patience, "normal")
    }

    func testTheWordsAreThePages() {
        XCTAssertEqual(TurnsCopy.setting, "Wait before answering")
        XCTAssertEqual(TurnsCopy.levels.map(\.value), ["quick", "normal", "patient"])
        XCTAssertEqual(TurnsCopy.levels.map(\.label), ["Quick", "Normal", "Patient"])
        XCTAssertEqual(TurnsCopy.holding, "Holding · say “go ahead” when you're done")
        XCTAssertEqual(TurnsCopy.defaultLevel, "normal")
    }
}
