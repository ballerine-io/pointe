import Foundation
import Testing
@testable import PointeKit

@Suite struct NewSessionModelTests {
    static let optionsJSON = """
    {"harnesses": [{"name": "claude-code", "title": "Claude Code", "available": true, "why": null},
                   {"name": "codex", "title": "Codex", "available": false, "why": "Codex is not installed on this Mac."}],
     "machines": [{"name": "studio", "here": true, "available": true, "why": null},
                  {"name": "devbox", "here": false, "available": false, "why": "Pointe starts sessions only on this Mac for now."}],
     "folders": [{"path": "/Users/mira/work/shop", "name": "shop", "source": "session"},
                 {"path": "/Users/mira/work/lantern", "name": "lantern", "source": "added"}],
     "max_prompt": 4000}
    """

    func options(_ json: String = optionsJSON) throws -> NewSession.Options {
        try JSONDecoder().decode(NewSession.Options.self, from: Data(json.utf8))
    }

    @Test func theOptionsDecodeAsTheDaemonSendsThem() throws {
        let o = try options()
        #expect(o.harnesses.map(\.title) == ["Claude Code", "Codex"])
        #expect(o.harnesses[1].available == false && o.harnesses[1].why == "Codex is not installed on this Mac.")
        #expect(o.machines[1].why?.hasPrefix("Pointe starts sessions only on this Mac") == true && o.showsMachines)
        #expect(o.folders.map(\.name) == ["shop", "lantern"] && o.folders[0].path == "/Users/mira/work/shop")
    }

    @Test func theSheetOpensOnWhatCanStart() throws {
        let draft = NewSession.Draft(try options())
        #expect(draft.harness == "claude-code" && draft.machine == "studio" && draft.folder == "/Users/mira/work/shop")
        #expect(draft.canStart(try options()))
    }

    @Test func theBodyCarriesThePickedPathAndLeavesEmptyFieldsOut() throws {
        var draft = NewSession.Draft(try options())
        #expect(draft.body == ["harness": "claude-code", "folder": "/Users/mira/work/shop", "machine": "studio"])
        draft.folder = "/Users/mira/work/lantern"
        draft.name = "  lantern-fix "
        draft.prompt = "Run the tests.\n"
        #expect(draft.body == ["harness": "claude-code", "folder": "/Users/mira/work/lantern", "machine": "studio",
                               "name": "lantern-fix", "prompt": "Run the tests."])
    }

    @Test func startIsNotOfferedWithoutAFolderOrForAnAgentThatCannotStart() throws {
        let o = try options()
        var draft = NewSession.Draft(o)
        draft.harness = "codex"
        #expect(!draft.canStart(o))
        draft.harness = "claude-code"
        draft.machine = "devbox"
        #expect(!draft.canStart(o))
        draft.machine = "studio"
        draft.folder = "/Users/mira/elsewhere"
        #expect(!draft.canStart(o))

        let none = NewSession.Options(harnesses: o.harnesses, machines: [], folders: [])
        let empty = NewSession.Draft(none)
        #expect(empty.folder == nil && empty.machine == nil && !empty.canStart(none) && !none.showsMachines)
        let noAgent = NewSession.Options(harnesses: [o.harnesses[1]], machines: [], folders: o.folders)
        #expect(NewSession.Draft(noAgent).harness == nil && !NewSession.Draft(noAgent).canStart(noAgent))
    }

    @Test func theStatusCarriesWhatIsStartingAndAReadBack() throws {
        let json = """
        {"connected": true, "sessions": [],
         "starting": [{"id": "s1", "name": "shop-2", "harness": "claude-code", "label": "Claude Code", "folder": "shop", "state": "waiting", "detail": "", "since": 1700000000},
                      {"id": "s2", "name": "lantern", "harness": "codex", "label": "Codex", "folder": "lantern", "state": "failed", "detail": "Codex's daemon is not running.", "since": 1700000001}],
         "start_pending": {"id": "p1", "line": "Start a Claude Code session in shop on studio, named shop-2? Say yes or tap.",
                           "harness": "claude-code", "name": "shop-2", "folder": "shop", "expires_in": 41.5}}
        """
        let status = try JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
        let rows = try #require(status.starting)
        #expect(rows.map(\.tag) == [NewSessionCopy.starting, NewSessionCopy.failed] && rows.map(\.agent) == ["Claude Code", "Codex"])
        #expect(rows[0].why == nil && rows[1].why == "Codex's daemon is not running.")
        #expect(status.start_pending == NewSession.Pending(id: "p1", line: "Start a Claude Code session in shop on studio, named shop-2? Say yes or tap."))
    }

    @Test func anOlderDaemonSendsNeitherAndNullIsNoReadBack() throws {
        let old = try JSONDecoder().decode(API.Status.self, from: Data(#"{"connected": false, "sessions": []}"#.utf8))
        #expect(old.starting == nil && old.start_pending == nil)
        let none = try JSONDecoder().decode(API.Status.self, from: Data(#"{"connected": false, "sessions": [], "starting": [], "start_pending": null}"#.utf8))
        #expect(none.starting == [] && none.start_pending == nil)
        #expect(NewSession.Starting(id: "s", name: "shop").agent == "Claude" && NewSession.Starting(id: "s", name: "shop").tag == "starting")
    }

    /// The client's requests, as the daemon reads them: the options are a GET; a start, a confirm and a cancel are POSTs
    /// with exactly these bodies.
    @Test func theClientAsksAndPostsWhatTheDaemonReads() throws {
        let endpoint = DaemonEndpoint(port: 7999, credential: .token("made-up"))
        #expect(endpoint.request("voice/new-session").url?.absoluteString == "http://127.0.0.1:7999/voice/new-session")
        let post = endpoint.request("voice/new-session", method: "POST", body: ["confirm": "p1"].mapValues(JSONValue.string))
        #expect(post.httpMethod == "POST")
        #expect(try JSONSerialization.jsonObject(with: try #require(post.httpBody)) as? [String: String] == ["confirm": "p1"])
        #expect(DaemonClient.reason(Data(#"{"detail": "A session is already called shop."}"#.utf8), code: 409) == "A session is already called shop.")
    }
}

@MainActor @Suite struct NewSessionStoreTests {
    func store(_ daemon: StubDaemon, auth: FakeAuth = FakeAuth(true)) -> PointeStore {
        PointeStore(api: daemon, authenticator: auth, appVersion: "1.15.0")
    }

    @Test func startAsksWhoIsThereThenShowsARowThatBecomesASession() async throws {
        let daemon = StubDaemon(), auth = FakeAuth(true)
        let s = store(daemon, auth: auth)
        await s.refresh()
        var draft = NewSession.Draft(try #require(await s.startOptions()))
        draft.folder = "/Users/mira/work/lantern"
        draft.prompt = "Run the tests."
        #expect(await s.start(draft))
        #expect(auth.reasons == [MacCopy.startReason])
        #expect(await daemon.calls == ["newSession folder=/Users/mira/work/lantern harness=claude-code machine=studio prompt=Run the tests."])
        #expect(s.starting.map(\.name) == ["lantern"] && s.starting.first?.tag == "starting" && s.starting.first?.agent == "Claude Code")
        #expect(!(s.status?.sessions ?? []).contains { $0.name == "lantern" })
        for _ in 0..<3 { await s.refresh() }
        #expect(s.starting.isEmpty && s.status?.sessions.last?.name == "lantern")
    }

    @Test func withoutTouchIDNothingStarts() async throws {
        let daemon = StubDaemon()
        let s = store(daemon, auth: FakeAuth(false))
        let draft = NewSession.Draft(try #require(await s.startOptions()))
        #expect(!(await s.start(draft)))
        await daemon.set { $0.start_pending = StubDaemon.readBack }
        await s.refresh()
        #expect(!(await s.confirmStart(try #require(s.startPending))))
        #expect(await daemon.calls.isEmpty && s.startPending != nil && s.starting.isEmpty)
    }

    @Test func aRefusedStartKeepsTheDaemonsReasonForTheSheet() async throws {
        let daemon = StubDaemon()
        let s = store(daemon)
        await s.refresh()
        var draft = NewSession.Draft(try #require(await s.startOptions()))
        draft.name = "payments"
        #expect(!(await s.start(draft)))
        #expect(s.startProblem == "A session is already called payments." && s.starting.isEmpty)
        draft.name = ""
        #expect(await s.start(draft))
        #expect(s.startProblem == nil)

        await daemon.setDown(true)
        #expect(await s.startOptions() == nil)
        #expect(s.startProblem == MacCopy.unreachable(MacCopy.thisMac))
    }

    @Test func theFoldersAddedForNewSessionsAreSetAsAWholeList() async throws {
        let daemon = StubDaemon()
        let s = store(daemon)
        await s.refresh()
        #expect(s.prefs?.sessionFolders == [])
        await s.setSessionFolders(["/Users/mira/work/lantern", "/Users/mira/work/shop"])
        #expect(await daemon.calls == ["setPrefs sessions.folders"])
        #expect(s.prefs?.sessionFolders == ["/Users/mira/work/lantern", "/Users/mira/work/shop"])
        let sent = DaemonEndpoint(port: 7999, credential: .token("made-up")).request("voice/prefs", method: "POST", body: ["sessions.folders": .strings(["/Users/mira/work/shop"])])
        #expect(try JSONSerialization.jsonObject(with: try #require(sent.httpBody)) as? [String: [String]] == ["sessions.folders": ["/Users/mira/work/shop"]])
    }

    @Test func aReadBackIsConfirmedAfterTouchIDAndCancelledWithout() async throws {
        let daemon = StubDaemon(), auth = FakeAuth(true)
        await daemon.set { $0.start_pending = StubDaemon.readBack }
        let s = store(daemon, auth: auth)
        await s.refresh()
        let pending = try #require(s.startPending)
        #expect(pending.line == "Start a Claude Code session in shop on studio, named shop-2? Say yes or tap.")
        #expect(await s.confirmStart(pending))
        #expect(auth.reasons == [MacCopy.startReason])
        #expect(await daemon.calls == ["newSession confirm=read-1"])
        #expect(s.startPending == nil && s.starting.map(\.name) == ["shop-2"])

        #expect(!(await s.confirmStart(pending)))  // answered already: the daemon says so
        #expect(s.notice == "That is no longer waiting for an answer.")

        await daemon.set { $0.start_pending = StubDaemon.readBack }
        await s.refresh()
        #expect(await s.cancelStart(pending))
        #expect(auth.reasons.count == 2)  // the two confirms; Cancel asked nothing
        #expect(await daemon.calls.last == "newSession cancel=read-1")
        #expect(s.startPending == nil && s.starting.map(\.name) == ["shop-2"])
    }
}
