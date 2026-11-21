import XCTest
@testable import PointeUI

/// Starting a new session from the phone (docs/design/new-session.md): what the status carries, what the app sends, and
/// how a refusal reads. The sheet's own rules (what Start needs, the body) are the package's, tested there.
final class NewSessionTests: XCTestCase {
    func testTheStatusCarriesWhatIsStartingAndAnOlderMacSendsNeither() throws {
        let status = try JSONDecoder().decode(API.Status.self, from: Data(Demo.newSessionJSON(pending: false).utf8))
        let rows = try XCTUnwrap(status.starting)
        XCTAssertEqual(rows.map(\.name), ["shop-2", "lantern"])
        XCTAssertEqual(rows.map(\.tag), [NewSessionCopy.starting, NewSessionCopy.failed])
        XCTAssertEqual(rows.map(\.agent), ["Claude Code", "Codex"])
        XCTAssertNil(rows[0].why)
        XCTAssertEqual(rows[1].why, "Codex's daemon is not running.")
        XCTAssertNil(status.start_pending)

        let old = try JSONDecoder().decode(API.Status.self, from: Data(#"{"connected": true, "sessions": []}"#.utf8))
        XCTAssertNil(old.starting)
        XCTAssertNil(old.start_pending)
    }

    func testAReadBackCarriesItsExactLine() throws {
        let demo = try XCTUnwrap(Demo.make(.startPending))
        XCTAssertEqual(demo.status.start_pending?.id, "rb-1")
        XCTAssertEqual(demo.status.start_pending?.line, "Start a Claude Code session in shop on studio, named shop-2? Say yes or tap.")
        XCTAssertEqual(demo.status.starting, [])
        XCTAssertNotNil(Demo.make(.newSession)?.status.starting?.first)
    }

    func testTheDemoOffersWhatCanStartAndSaysWhyTheRestCannot() throws {
        let options = try XCTUnwrap(Demo.startOptions, "the fixture decodes")
        XCTAssertEqual(options.harnesses.filter(\.available).map(\.title), ["Claude Code", "OpenCode"])
        XCTAssertEqual(options.harnesses.last?.why, "Codex is not installed on this Mac.")
        XCTAssertTrue(options.showsMachines)
        XCTAssertEqual(options.machines.last?.available, false)
        let draft = NewSession.Draft(options)
        XCTAssertTrue(draft.canStart(options))
        XCTAssertEqual(draft.body, ["harness": "claude-code", "folder": "/Users/mira/work/shop", "machine": "studio"])
    }

    // MARK: what the app sends (the Mac's route: /voice/new-session)

    private func api(_ status: Int, _ reply: String) -> API {
        HubStub.reply = (status, reply); HubStub.bodies = []
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [HubStub.self]
        return API(pairing: Demo.pairing, session: URLSession(configuration: config))
    }

    func testTheOptionsAreAskedForAndDecoded() async throws {
        let reply = #"{"harnesses": [{"name": "codex", "title": "Codex", "available": true, "why": null}], "machines": [{"name": "studio", "here": true, "available": true, "why": null}], "folders": [], "max_prompt": 4000}"#
        let options = try await api(200, reply).startOptions()
        XCTAssertEqual(HubStub.bodies.first?["path"] as? String, "/voice/new-session")
        XCTAssertEqual(options.harnesses.map(\.name), ["codex"])
        XCTAssertFalse(options.showsMachines)
        XCTAssertFalse(NewSession.Draft(options).canStart(options), "no folder: nothing to start in")
    }

    func testStartSendsThePickedPathAndOnlyTheFieldsFilledIn() async throws {
        var draft = NewSession.Draft(try XCTUnwrap(Demo.startOptions))
        draft.harness = "opencode"
        draft.folder = "/Users/mira/work/lantern"
        draft.prompt = " Run the tests. "
        try await api(200, #"{"id": "st-9", "name": "lantern"}"#).newSession(draft.body)
        XCTAssertEqual(HubStub.bodies.first?["path"] as? String, "/voice/new-session")
        XCTAssertEqual(HubStub.bodies.first?["body"] as? [String: String],
                       ["harness": "opencode", "folder": "/Users/mira/work/lantern", "machine": "studio", "prompt": "Run the tests."])
    }

    func testTheCardsButtonsSendConfirmOrCancelWithTheId() async throws {
        try await api(200, #"{"id": "st-9", "name": "shop-2"}"#).newSession(["confirm": "rb-1"])
        XCTAssertEqual(HubStub.bodies.first?["body"] as? [String: String], ["confirm": "rb-1"])
        try await api(200, #"{"cancelled": true}"#).newSession(["cancel": "rb-1"])
        XCTAssertEqual(HubStub.bodies.first?["body"] as? [String: String], ["cancel": "rb-1"])
    }

    @MainActor
    func testARefusalIsShownInTheMacsOwnWords() async {
        do {
            try await api(409, #"{"detail": "A session is already called shop."}"#).newSession(["harness": "codex"])
            XCTFail("a 409 is a refusal")
        } catch {
            XCTAssertEqual(NewSessionSheet.refusal(error), "A session is already called shop.")
        }
        do { _ = try await api(404, "").startOptions(); XCTFail() } catch {
            XCTAssertEqual(NewSessionSheet.refusal(error), "Pointe on the Mac does not start sessions yet: update it.")
        }
        XCTAssertEqual(NewSessionSheet.refusal(URLError(.timedOut)), "The Mac did not answer.")
    }
}
