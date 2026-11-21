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

    /// The client's requests, as the daemon reads them: the options are a GET; a start, a confirm and a cancel are POSTs
    /// with exactly these bodies.
    @Test func theClientAsksAndPostsWhatTheDaemonReads() throws {
        let endpoint = DaemonEndpoint(port: 7999, credential: .token("made-up"))
        #expect(endpoint.request("voice/new-session").url?.absoluteString == "http://127.0.0.1:7999/voice/new-session")
        let post = endpoint.request("voice/new-session", method: "POST", body: ["confirm": "p1"].mapValues(JSONValue.string))
        #expect(post.httpMethod == "POST")
        #expect(try JSONSerialization.jsonObject(with: try #require(post.httpBody)) as? [String: String] == ["confirm": "p1"])
    }
}
