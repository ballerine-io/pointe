import XCTest
@testable import PointeKit

/// The Add sessions sheet's listing (docs/design/attach-by-voice.md): what the Mac sends decodes, the search keeps what
/// fits, and the sections are open first, then this week's, each by machine.
final class AddSessionsTests: XCTestCase {
    private let json = """
    {"machines": [], "reopen_here": true,
     "open": [{"key": "-|claude-code|a1", "machine": "studio", "here": true, "harness": "claude-code", "label": "Claude Code",
               "name": "pentest-recon", "folder": "pentest-notes", "path": "/Users/mira/work/pentest-notes", "state": "open",
               "when": 1, "ago": "5 minutes ago", "branch": "recon", "title": "", "first": "Plan the pentest", "last": "",
               "kind": "interactive", "status": "idle", "approvals": true, "joinable": true, "why": null},
              {"key": "devbox|codex|t1", "machine": "devbox", "here": false, "harness": "codex", "label": "Codex", "name": "invoices",
               "folder": "billing", "path": "/srv/billing", "state": "open", "when": 1, "ago": "just now", "branch": "",
               "title": "", "first": "", "last": "", "kind": "", "status": "", "approvals": false, "joinable": true, "why": null}],
     "recent": [{"key": "-|claude-code|c3", "machine": "studio", "here": true, "harness": "claude-code", "label": "Claude Code",
                 "name": "billing-migration", "folder": "billing", "path": "/Users/mira/work/billing", "state": "recent", "when": 1,
                 "ago": "from yesterday", "branch": "main", "title": "billing-migration", "first": "Write the migration", "last": "",
                 "kind": "", "status": "", "approvals": true, "joinable": false, "why": "Its folder is no longer there."}]}
    """

    func testTheListingDecodesAndGroupsOpenFirstThenByMachine() throws {
        let listing = try JSONDecoder().decode(AddSessions.Listing.self, from: Data(json.utf8))
        let sections = listing.sections("")
        XCTAssertEqual(sections.map(\.title), [AddSessionsCopy.open, AddSessionsCopy.recent])
        XCTAssertEqual(sections[0].machines.map(\.name), ["studio", "devbox"])
        XCTAssertEqual(listing.recent[0].why, "Its folder is no longer there.")
        XCTAssertEqual(listing.open[0].detail, "pentest-notes · recon · 5 minutes ago")
    }

    func testTheSearchKeepsEverySessionEveryWordFits() throws {
        let listing = try JSONDecoder().decode(AddSessions.Listing.self, from: Data(json.utf8))
        XCTAssertEqual(listing.sections("pentest").flatMap { $0.machines.flatMap(\.items) }.map(\.name), ["pentest-recon"])
        XCTAssertEqual(listing.sections("billing devbox").flatMap { $0.machines.flatMap(\.items) }.map(\.name), ["invoices"])
        XCTAssertTrue(listing.sections("kubernetes").isEmpty)
    }

    func testAReadBackThatAsksWhichHasNoJoinButton() {
        XCTAssertEqual(AddSessions.Pending(id: "a", line: "x", choose: false, verb: "reopen").button, AddSessionsCopy.reopen)
        XCTAssertTrue(AddSessions.Pending(id: "a", line: "x", choose: true).choose)
    }
}
