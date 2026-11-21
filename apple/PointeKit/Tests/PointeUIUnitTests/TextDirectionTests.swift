import SwiftUI
import XCTest
@testable import PointeUI

/// One rule for every message: its first strong letter decides, as the browser's dir="auto" does on the page.
final class TextDirectionTests: XCTestCase {
    func testRightToLeftScriptsReadFromTheRight() {
        XCTAssertEqual(TextDirection.of("שלחתי את התיקון לבדיקה."), .rightToLeft)       // Hebrew
        XCTAssertEqual(TextDirection.of("أرسلت الإصلاح للمراجعة."), .rightToLeft)        // Arabic
        XCTAssertEqual(TextDirection.of("این را بفرست."), .rightToLeft)                  // Persian
        XCTAssertEqual(TextDirection.of("یہ بھیج دو۔"), .rightToLeft)                    // Urdu
    }

    func testMixedTextTakesTheDirectionItStartsIn() {
        XCTAssertEqual(TextDirection.of("פתחתי PR חדש ל-billing."), .rightToLeft)
        XCTAssertEqual(TextDirection.of("Send it to the תור team."), .leftToRight)
    }

    func testDigitsAndPunctuationFirstDoNotDecide() {
        XCTAssertEqual(TextDirection.of("42 בדיקות עברו."), .rightToLeft)
        XCTAssertEqual(TextDirection.of("“٤٢ اختبارا نجحت.”"), .rightToLeft)  // Arabic-Indic digits are not letters
        XCTAssertEqual(TextDirection.of("— 3, then ok."), .leftToRight)
        XCTAssertEqual(TextDirection.of("42."), .leftToRight)   // no letter at all: left to right
        XCTAssertEqual(TextDirection.of(""), .leftToRight)
    }

    func testTheChallengePanelUsesTheSameRule() {
        XCTAssertTrue(ChallengeCopy.rightToLeft("  42 תור"))
        XCTAssertFalse(ChallengeCopy.rightToLeft("A queue, then תור"))
    }
}

final class IsolatedTests: XCTestCase {
    func testAMessageInsideOurSentenceIsIsolated() {
        XCTAssertEqual(TextDirection.isolated("שלום."), "\u{2068}שלום.\u{2069}")
    }
}
