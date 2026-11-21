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

    @Test func theDaemonIsFoundVerifiedAndOpenedByThePageKey() async throws {
        #expect(locator.paths.port != DaemonPaths.defaultPort, "never the live daemon")
        guard case .running = await locator.state() else { Issue.record("the daemon is not running, or is not the listener"); return }
        let client = DaemonClient(endpoint: try await locator.endpoint())
        let status = try await client.status()
        #expect(status.version != nil)
        _ = try await client.prefs()
        // Without the key the same listener answers 403: the cookie is what opened it.
        let bare = DaemonClient(endpoint: DaemonEndpoint(port: locator.paths.port, credential: .pageKey("not-the-key")))
        await #expect(throws: API.Failure.self) { _ = try await bare.status() }
    }

    /// `live.py approve` holds a request open and runs this: Approve it as the app's click does.
    @Test(.enabled(if: ProcessInfo.processInfo.environment["POINTE_E2E_APPROVE"] != nil))
    func aClicksApproveReachesTheWaitingSession() async throws {
        let client = DaemonClient(endpoint: try await locator.endpoint())
        var waiting: API.Session?
        for _ in 0..<120 where waiting == nil {
            waiting = try await client.status().sessions.first { $0.waiting && $0.request_id != nil }
            if waiting == nil { try await Task.sleep(for: .milliseconds(500)) }
        }
        let session = try #require(waiting, "no request came")
        let id = try #require(session.request_id)
        try await Task.sleep(for: .seconds(3))  // long enough for the window to show the card
        try await client.answer(session: session.name, requestId: id, allow: true, viaNotification: false)
        await #expect(throws: API.Failure.status(409, "that request is no longer pending")) {
            try await client.answer(session: session.name, requestId: id, allow: true, viaNotification: false)
        }
    }
}
#endif
