import XCTest
@testable import Pointe

/// Show while it says: the contract decodes (and an older Mac without it still does), and the sheet's tab follows the
/// voice until you tap one or pin one.
final class ShowTests: XCTestCase {
    private func status(_ json: String) throws -> API.Status {
        try JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    private let set3 = #"""
    {"id": "s3", "session": "billing", "since": 1700000000, "summary": "pricing.py · edited 40–42 · 1 failing test",
     "current": "s3a1", "artifacts": [
       {"id": "s3a0", "kind": "test", "name": "test output", "path": "", "range": null, "failed": true},
       {"id": "s3a1", "kind": "edit", "name": "pricing.py", "path": "pricing.py", "range": [40, 42], "failed": false},
       {"id": "s3a2", "kind": "read", "name": "id_rsa", "path": "/home/x/id_rsa", "range": null, "failed": false,
        "refused": "outside the project: not shown"}]}
    """#

    private func showing(_ json: String) throws -> API.Showing {
        try JSONDecoder().decode(API.Showing.self, from: Data(json.utf8))
    }

    func testAnOlderMacWithoutTheFeatureDecodesAndShowsNothing() throws {
        let s = try status(#"{"connected": true, "sessions": []}"#)
        XCTAssertNil(s.showing)
        XCTAssertNil(s.show_on_phone)
        XCTAssertNil(s.shown_earlier)
    }

    func testTheStatusContractDecodes() throws {
        let s = try status(#"{"connected": true, "sessions": [], "show_on_phone": true, "showing": \#(set3), "shown_earlier": [{"id": "s3", "session": "billing", "at": 1700000000, "summary": "x", "artifacts": []}]}"#)
        let shown = try XCTUnwrap(s.showing)
        XCTAssertEqual(shown.current, "s3a1")
        XCTAssertEqual(shown.artifacts.map(\.kind), ["test", "edit", "read"])
        XCTAssertEqual(shown.artifacts[1].range, [40, 42])
        XCTAssertEqual(shown.artifacts[2].refused, "outside the project: not shown")
        XCTAssertEqual(s.shown_earlier?.first?.id, "s3")
        XCTAssertEqual(s.show_on_phone, true)
    }

    func testTheArtifactContractDecodes() throws {
        let file = try JSONDecoder().decode(API.ArtifactView.self, from: Data(#"""
        {"id": "s3a1", "kind": "edit", "name": "pricing.py", "path": "pricing.py", "range": [40, 42], "failed": false,
         "lines": [{"n": 40, "text": "x", "hl": true}], "total": 100, "truncated": true, "changed_since": true, "diff": "+x"}
        """#.utf8))
        XCTAssertEqual(file.lines?.first, API.ArtifactLine(n: 40, text: "x", hl: true))
        XCTAssertEqual(file.changed_since, true)
        XCTAssertEqual(file.diff, "+x")
        let test = try JSONDecoder().decode(API.ArtifactView.self, from: Data(#"""
        {"id": "s3a0", "kind": "test", "name": "test output", "path": "", "range": null, "failed": true,
         "command": "pytest", "output": "a\nb", "focus": 1, "truncated": false}
        """#.utf8))
        XCTAssertEqual(test.focus, 1)
        let refused = try JSONDecoder().decode(API.ArtifactView.self, from: Data(#"{"id": "a", "kind": "read", "problem": "binary: not shown (4 kB)"}"#.utf8))
        XCTAssertEqual(refused.problem, "binary: not shown (4 kB)")
        XCTAssertNil(refused.lines)
    }

    func testThePrefDefaultsOff() throws {
        XCTAssertFalse(try JSONDecoder().decode(API.Prefs.self, from: Data("{}".utf8)).showOnPhone)
        XCTAssertTrue(try JSONDecoder().decode(API.Prefs.self, from: Data(#"{"show.on_phone": true}"#.utf8)).showOnPhone)
    }

    func testTheTabFollowsTheVoiceUntilYouPickOne() throws {
        var follow = ShowFollow()
        var shown = try showing(set3)
        follow.follow(shown)
        XCTAssertEqual(follow.selected(shown), "s3a1", "the one the voice names")
        follow.picked = "s3a0"
        XCTAssertEqual(follow.selected(shown), "s3a0", "your tap outranks the voice")
        shown = try showing(set3.replacingOccurrences(of: #""current": "s3a1""#, with: #""current": "s3a2""#))
        follow.follow(shown)  // same report: the tap stays
        XCTAssertEqual(follow.selected(shown), "s3a0")
        let next = try showing(set3.replacingOccurrences(of: "s3", with: "s4"))
        follow.follow(next)  // a new report forgets the tap
        XCTAssertEqual(follow.selected(next), "s4a1")
    }

    func testAPinStaysAcrossReportsAndIsATab() throws {
        var follow = ShowFollow()
        let shown = try showing(set3)
        follow.follow(shown)
        follow.togglePin(shown.artifacts[1], session: "billing")
        let next = try showing(set3.replacingOccurrences(of: "s3", with: "s4"))
        follow.follow(next)
        XCTAssertEqual(follow.selected(next), "s3a1", "pinned from the earlier report")
        XCTAssertEqual(follow.tabs(next).map(\.id), ["s3a1", "s4a0", "s4a1", "s4a2"])
        follow.togglePin(shown.artifacts[1], session: "billing")
        XCTAssertEqual(follow.selected(next), "s4a1", "unpinned: back to following the voice")
        XCTAssertEqual(follow.tabs(next).count, 3)
    }

    func testNothingShownSelectsNothing() {
        XCTAssertNil(ShowFollow().selected(nil))
    }

    func testTheRangeCopyMatchesThePage() {
        XCTAssertEqual(ShowCopy.range([40, 62]), "lines 40–62")
        XCTAssertEqual(ShowCopy.range([7, 7]), "line 7")
        XCTAssertNil(ShowCopy.range(nil))
        XCTAssertEqual(ShowCopy.card("pricing.py · edited 40–62"), "Showing: pricing.py · edited 40–62")
    }

    func testTheDemoFixturesDecode() {
        for id in ["s3a0", "s3a1", "s3a2", "s2a0"] { XCTAssertNotNil(Demo.artifact(id), id) }
        XCTAssertNil(Demo.artifact("nope"))
    }
}
