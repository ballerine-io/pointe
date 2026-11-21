#if os(macOS)
import Foundation
import PointeKit
import Testing
@testable import PointeMacKit

/// Against a real daemon with its own state and port, run by macos/e2e/live.py (never the one on 7860): the locator
/// finds it and checks the listener, the page key opens it, and a click's Approve reaches the session that waits.
@Suite(.enabled(if: ProcessInfo.processInfo.environment["POINTE_E2E_STATE"] != nil))
struct LiveDaemonTests {
    let locator: DaemonLocator

    init() {
        let env = ProcessInfo.processInfo.environment
        locator = DaemonLocator(environment: ["CLAUDE_VOICE_STATE": env["POINTE_E2E_STATE"] ?? "", "CLAUDE_VOICE_DAEMON_PORT": env["POINTE_E2E_PORT"] ?? ""])
    }

    private func ask(_ request: URLRequest) async throws -> (Int, [String: Any]) {
        let (data, response) = try await DaemonEndpoint.session().data(for: request)
        return ((response as? HTTPURLResponse)?.statusCode ?? 0, (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:])
    }

    @Test func theDaemonIsFoundVerifiedAndOpenedByThePageKey() async throws {
        #expect(locator.paths.port != DaemonPaths.defaultPort, "never the live daemon")
        guard case .running = await locator.state() else { Issue.record("the daemon is not running, or is not the listener"); return }
        let endpoint = try await locator.endpoint()
        let (code, status) = try await ask(endpoint.request("voice/status"))
        #expect(code == 200 && status["version"] != nil)
        #expect(try await ask(endpoint.request("voice/prefs")).0 == 200)
        // Without the key the same listener answers 403: the cookie is what opened it.
        let bare = DaemonEndpoint(port: locator.paths.port, credential: .pageKey("not-the-key"))
        #expect(try await ask(bare.request("voice/status")).0 == 403)
    }

    /// `live.py approve` holds a request open and runs this: Approve it as the app's click does.
    @Test(.enabled(if: ProcessInfo.processInfo.environment["POINTE_E2E_APPROVE"] != nil))
    func aClicksApproveReachesTheWaitingSession() async throws {
        let endpoint = try await locator.endpoint()
        var waiting: [String: Any]?
        for _ in 0..<120 where waiting == nil {
            let sessions = try await ask(endpoint.request("voice/status")).1["sessions"] as? [[String: Any]] ?? []
            waiting = sessions.first { $0["waiting"] as? Bool == true && $0["request_id"] is String }
            if waiting == nil { try await Task.sleep(for: .milliseconds(500)) }
        }
        let session = try #require(waiting, "no request came")
        let body: [String: JSONValue] = ["session": .string(session["name"] as? String ?? ""), "request_id": .string(session["request_id"] as? String ?? ""),
                                         "decision": "allow"]
        try await Task.sleep(for: .seconds(3))  // long enough for the window to show the card
        #expect(try await ask(endpoint.request("voice/approve", method: "POST", body: body)).0 == 200)
        let again = try await ask(endpoint.request("voice/approve", method: "POST", body: body))
        #expect(again.0 == 409 && again.1["detail"] as? String == "that request is no longer pending")
    }
}
#endif
