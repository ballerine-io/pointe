import XCTest
@testable import PointeUI

/// The composer: Return sends, and a new line is Shift+Return or Option+Return on a keyboard, the New line key on the
/// iPhone. What was typed reaches the Mac with its line breaks.
final class ComposerTests: XCTestCase {
    func testReturnSendsAndShiftOrOptionReturnIsANewLine() {
        XCTAssertEqual(Composer.returnKey(shift: false, option: false), .send)
        XCTAssertEqual(Composer.returnKey(shift: true, option: false), .newLine)
        XCTAssertEqual(Composer.returnKey(shift: false, option: true), .newLine)
        XCTAssertEqual(Composer.returnKey(shift: true, option: true), .newLine)
    }

    func testTheNewLineKeyInsertsAtTheCursorOrAtTheEnd() {
        XCTAssertEqual(Composer.newLine(in: "first", at: nil).text, "first\n")
        let text = "first second"
        let cursor = text.index(text.startIndex, offsetBy: 5)
        let out = Composer.newLine(in: text, at: cursor..<cursor)
        XCTAssertEqual(out.text, "first\n second")
        XCTAssertEqual(out.text[out.cursor...], " second", "the cursor sits after the new line")
        let picked = text.index(text.startIndex, offsetBy: 5)..<text.index(text.startIndex, offsetBy: 6)
        XCTAssertEqual(Composer.newLine(in: text, at: picked).text, "first\nsecond", "a selection is replaced")
    }

    func testReturnTypedOnTheSoftKeyboardSendsAndTheNewLineKeyDoesNot() {
        // The field is multi-line, so Return writes "\n" into it: that is Send.
        XCTAssertEqual(Composer.fieldChanged(old: "hello", new: "hello\n", expected: nil), .send("hello"))
        XCTAssertEqual(Composer.fieldChanged(old: "hel lo", new: "hel\n lo", expected: nil), .send("hel lo"), "Return mid-line sends too")
        // The New line key's own "\n" stays.
        XCTAssertEqual(Composer.fieldChanged(old: "hello", new: "hello\n", expected: "hello\n"), .keep)
        // Typing, pasting several lines, deleting: kept as they are.
        XCTAssertEqual(Composer.fieldChanged(old: "hel", new: "hell", expected: nil), .keep)
        XCTAssertEqual(Composer.fieldChanged(old: "", new: "a\nb", expected: nil), .keep)
        XCTAssertEqual(Composer.fieldChanged(old: "a\nb", new: "ab", expected: nil), .keep)
    }

    func testAMultiLineDraftIsSentWhole() {
        XCTAssertEqual(Composer.sendable("  Rename the column.\nThen migrate.\n\n"), "Rename the column.\nThen migrate.")
        XCTAssertNil(Composer.sendable(" \n \n"))
    }

    func testTheWords() {
        XCTAssertEqual(Composer.newLineLabel, "New line")
    }
}
