#if os(macOS)
import AppKit
import XCTest
@testable import PointeUI

/// A pairing code on the clipboard (SECURITY.md, "The iPhone app"): marked concealed, so clipboard managers and
/// history tools skip it, and gone when the code ends unless something else was copied since. A private pasteboard,
/// never the person's own.
@MainActor
final class ClipboardTests: XCTestCase {
    private var board: NSPasteboard!

    override func setUp() async throws { board = NSPasteboard(name: .init("io.ballerine.pointe.tests.\(UUID().uuidString)")) }
    override func tearDown() async throws { board.releaseGlobally() }

    func testASecretIsConcealedAndClearedWhenItsCodeEnds() async throws {
        Clipboard.copy("pointe node join made-up-line", until: Date().addingTimeInterval(0.3), on: board)
        XCTAssertEqual(board.string(forType: .string), "pointe node join made-up-line")
        XCTAssertTrue(board.types?.contains(Clipboard.concealed) == true, "marked concealed")
        try await Task.sleep(for: .seconds(0.8))
        XCTAssertNil(board.string(forType: .string), "cleared when the code ends")
    }

    func testWhatWasCopiedAfterIsLeftAlone() async throws {
        Clipboard.copy("pointe node join made-up-line", until: Date().addingTimeInterval(0.3), on: board)
        board.clearContents()
        board.setString("the person's own text", forType: .string)
        try await Task.sleep(for: .seconds(0.8))
        XCTAssertEqual(board.string(forType: .string), "the person's own text")
    }
}
#endif
