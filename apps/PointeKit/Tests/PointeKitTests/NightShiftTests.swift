import Foundation
import Testing
@testable import PointeKit

@Suite struct NightShiftModelTests {
    static let optionsJSON = """
    {"shift": null, "history": [], "caps": {"hours": 8.0, "messages": 40, "notify": false},
     "limits": {"hours": 12.0, "messages": 200, "sessions": 8, "tasks": 5, "task_chars": 2000, "followups": 3},
     "rule": "I approve nothing: a session that needs approval waits for you.", "pending": null,
     "sessions": [{"name": "billing", "harness": "claude-code", "available": true, "why": null},
                  {"name": "docs", "harness": "opencode", "available": true, "why": null},
                  {"name": "shop", "harness": "codex", "available": false, "why": "shop is on another machine."}]}
    """
    static let startingJSON = """
    {"harnesses": [{"name": "claude-code", "title": "Claude Code", "available": false, "why": "Not installed."},
                   {"name": "codex", "title": "Codex", "available": true, "why": null}],
     "machines": [], "folders": [{"path": "/Users/mira/work/shop", "name": "shop"}]}
    """

    func options(_ json: String = optionsJSON) throws -> NightShift.Options {
        try JSONDecoder().decode(NightShift.Options.self, from: Data(json.utf8))
    }

    func summary(_ json: String) throws -> NightShift.Summary {
        try JSONDecoder().decode(NightShift.Summary.self, from: Data(json.utf8))
    }

    func json(_ body: [String: any Sendable]) throws -> NSDictionary {
        try #require(try JSONSerialization.jsonObject(with: JSONSerialization.data(withJSONObject: body)) as? NSDictionary)
    }

    @Test func theOptionsDecodeAsTheDaemonSendsThem() throws {
        let o = try options()
        #expect(o.shift == nil && o.history.isEmpty && o.pending == nil)
        #expect(o.caps == NightShift.Options.Caps(hours: 8, messages: 40, notify: false))
        #expect(o.limits == NightShift.Options.Limits(hours: 12, messages: 200, sessions: 8, tasks: 5))
        #expect(o.sessions.map(\.name) == ["billing", "docs", "shop"])
        #expect(o.sessions[2].available == false && o.sessions[2].why == "shop is on another machine.")
    }

    @Test func aReplyWithPartsMissingStillDecodes() throws {
        let o = try options(#"{"shift": {"id": "ns-1", "on": true}}"#)
        #expect(o.caps == NightShift.Options.Caps() && o.limits == NightShift.Options.Limits() && o.sessions.isEmpty)
        let shift = try #require(o.shift)
        #expect(shift.on && shift.id == "ns-1" && shift.headline == nil)
        #expect(shift.ledger == NightShift.Ledger() && shift.ledger.sections.isEmpty)
        #expect(shift.summary.statusLine == "0 of 0 done · 0 blocked")
    }

    @Test func theStatusLineSaysWhatIsDoneAndWhatIsBlocked() throws {
        #expect(try summary(#"{"id": "a", "on": true, "tasks": 3, "done": 1, "blocked": 1}"#).statusLine == "1 of 3 done · 1 blocked")
        #expect(try summary(#"{"id": "a", "on": true, "tasks": 3, "done": 3, "blocked": 0}"#).statusLine == "3 of 3 done · 0 blocked")
        #expect(try summary(#"{"id": "a", "on": false, "tasks": 5, "done": 2, "blocked": 2, "why": "stopped"}"#).statusLine == "2 of 5 done · 2 blocked")
    }

    /// A product rule: what was decided without the person and what waits on them come first.
    @Test func theLedgersPartsComeInTheProductsOrder() throws {
        #expect(NightShift.Section.allCases == [.decided, .asked, .done, .blocked, .inFlight, .notStarted])
        #expect(NightShift.Section.allCases.map(\.title) == [NightShiftCopy.decided, NightShiftCopy.asked, NightShiftCopy.done,
                                                             NightShiftCopy.blocked, NightShiftCopy.inFlight, NightShiftCopy.notStarted])
        let entry = #"{"id": "e", "session": "billing", "task": "t"}"#
        let ledger = try JSONDecoder().decode(NightShift.Ledger.self, from: Data("""
        {"not_started": [{"session": "shop", "task": "update the README"}], "blocked": [\(entry)], "done": [\(entry), \(entry)],
         "decided": [\(entry)], "in_flight": [], "asked": []}
        """.utf8))
        #expect(ledger.sections == [.decided, .done, .blocked, .notStarted], "an empty part is not shown")
        #expect(ledger.count(.done) == 2 && ledger.count(.inFlight) == 0)
        #expect(ledger.done[0].proof == "" && ledger.done[0].request == "", "a field that is not set is empty")
    }

    @Test func theSheetOpensOnTheFirstSessionAndTheMacsCaps() throws {
        let o = try options()
        let draft = NightShift.Draft(o)
        #expect(draft.rows.count == 1 && draft.rows[0].session == "billing" && !draft.rows[0].starts)
        #expect(draft.hours == 8 && draft.messages == 40 && draft.notify == false)
        let over = try options(#"{"caps": {"hours": 20, "messages": 500, "notify": true}}"#)
        let capped = NightShift.Draft(over)
        #expect(capped.hours == 12 && capped.messages == 200 && capped.notify, "never past the limits")
    }

    @Test func startNeedsATaskAndWhereItGoes() throws {
        let o = try options()
        var draft = NightShift.Draft(o)
        #expect(!draft.canStart(o), "no task yet")
        draft.rows[0].task = "   \n"
        #expect(!draft.canStart(o), "white space is not a task")
        draft.rows[0].task = "fix the retry tests"
        #expect(draft.canStart(o))
        draft.addRow(o)
        #expect(draft.rows.map(\.id) == [0, 1] && draft.canStart(o), "an empty row is left out, it does not hold Start back")
        draft.rows[1].task = "update the changelog"
        draft.rows[1].session = "shop"
        #expect(!draft.canStart(o), "a session that cannot take a task")
        draft.rows[1].session = "gone"
        #expect(!draft.canStart(o), "a session the Mac did not offer")
        draft.rows[1].starts = true
        #expect(!draft.canStart(o), "a new session with no agent and no folder")
        draft.rows[1].harness = "codex"
        #expect(!draft.canStart(o), "and with no folder")
        draft.rows[1].folder = "/Users/mira/work/shop"
        #expect(draft.canStart(o))
    }

    @Test func withNoSessionARowIsANewSessionWithTheFirstAgentThatCanStart() throws {
        let none = try options(#"{"sessions": []}"#)
        let starting = try JSONDecoder().decode(NewSession.Options.self, from: Data(Self.startingJSON.utf8))
        var draft = NightShift.Draft(none, starting: starting)
        #expect(draft.rows[0].starts && draft.rows[0].harness == "codex" && draft.rows[0].folder == "/Users/mira/work/shop")
        draft.rows[0].task = "fix the flaky test"
        #expect(draft.canStart(none))
        let alone = NightShift.Draft(none)
        #expect(!alone.rows[0].starts && alone.rows[0].session == nil && !alone.canStart(none))
    }

    @Test func theBodyIsWhatTheDaemonReads() throws {
        let o = try options()
        var draft = NightShift.Draft(o)
        draft.rows[0].task = "  finish the retry work and open a PR\n"
        draft.addRow(o)  // left empty: not sent
        draft.addRow(o)
        draft.rows[2].starts = true
        draft.rows[2].harness = "codex"
        draft.rows[2].folder = "/Users/mira/work/shop"
        draft.rows[2].task = "fix the flaky test"
        draft.hours = 6
        draft.messages = 25
        draft.notify = true
        let expected: NSDictionary = [
            "action": "start",
            "items": [["session": "billing", "task": "finish the retry work and open a PR"],
                      ["start": ["harness": "codex", "folder": "/Users/mira/work/shop"], "task": "fix the flaky test"]],
            "hours": 6, "messages": 25, "notify": true,
        ]
        #expect(try json(draft.body) == expected)
    }

    @Test func rowsStopAtWhatAShiftMayHold() throws {
        let o = try options(#"{"limits": {"hours": 12, "messages": 200, "sessions": 1, "tasks": 2}}"#)
        var draft = NightShift.Draft(o)
        #expect(draft.canAdd(o))
        draft.addRow(o)
        #expect(!draft.canAdd(o))
    }

    @Test func aReadBackCarriesItsExactLine() throws {
        let p = try JSONDecoder().decode(NightShift.Pending.self, from: Data(#"{"id": "sp-1", "line": "Night shift. Start? Say yes or tap.", "items": [], "expires_in": 48}"#.utf8))
        #expect(p.id == "sp-1" && p.line == "Night shift. Start? Say yes or tap.")
    }
}
