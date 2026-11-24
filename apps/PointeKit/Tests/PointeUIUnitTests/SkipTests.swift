import XCTest
@testable import PointeUI

/// Skip (docs/features/skip.md) and the conversation's Copy. The skip button shows only while Pointe's voice is heard,
/// with the page's words; Copy takes the words a bubble reads as.
final class SkipTests: XCTestCase {
    private func words(_ name: String, in file: String) throws -> String {
        let source = try String(contentsOf: Repo.root.appendingPathComponent(file), encoding: .utf8)
        let found = try XCTUnwrap(source.range(of: "\"\(name)\": \"", options: []) ?? source.range(of: "\(name): '"), "\(name) in \(file)")
        let rest = source[found.upperBound...]
        return String(rest[..<(rest.firstIndex(where: { $0 == "\"" || $0 == "'" }) ?? rest.endIndex)])
    }

    func testTheWordsAreTheDaemonsAndThePages() throws {
        for file in ["pointe/skip.py", "pointe/ui_skip.html"] {
            XCTAssertEqual(try words("skip", in: file), SkipCopy.skip, file)
            XCTAssertEqual(try words("failed", in: file), SkipCopy.failed, file)
        }
    }

    func testTheButtonShowsOnlyWhilePointesVoiceIsHeard() {
        XCTAssertTrue(SkipRule.shows(speaking: true, muted: false))
        XCTAssertFalse(SkipRule.shows(speaking: false, muted: false), "nothing is being said: nothing to skip")
        XCTAssertFalse(SkipRule.shows(speaking: true, muted: true), "muted, Pointe writes: nothing is heard")
    }

    func testTheRouteIsTheDaemons() throws {
        let api = try String(contentsOf: Repo.root.appendingPathComponent("apps/PointeKit/Sources/PointeUI/API.swift"), encoding: .utf8)
        let daemon = try String(contentsOf: Repo.root.appendingPathComponent("pointe/daemon.py"), encoding: .utf8)
        XCTAssertTrue(api.contains(#"post("voice/skip")"#) && daemon.contains(#"@app.post("/voice/skip")"#))
    }

    private func turn(_ json: String) throws -> API.Turn { try JSONDecoder().decode(API.Turn.self, from: Data(json.utf8)) }

    func testCopyTakesTheWordsTheBubbleReadsAs() throws {
        let pointe = try turn(#"{"id": 2, "who": "assistant", "text": "All 12 tests pass."}"#)
        XCTAssertEqual(Bubble.copyText(pointe, polish: true), "All 12 tests pass.")
        let mine = try turn(#"{"id": 3, "who": "user", "text": "um run the the tests", "understood": "Run the tests.", "typed": true}"#)
        XCTAssertEqual(Bubble.copyText(mine, polish: true), "Run the tests.", "the cleaned line, as the bubble shows it")
        XCTAssertEqual(Bubble.copyText(mine, polish: false), "um run the the tests", "with clean-up off the bubble shows what was heard")
        XCTAssertEqual(CopyCopy.copy, "Copy")
    }
}
