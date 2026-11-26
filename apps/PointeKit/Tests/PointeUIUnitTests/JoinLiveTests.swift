#if os(macOS)
import XCTest
@testable import PointeUI

/// The phone half of tests/test_integration_join.py, through the iPhone app's own code against a real hub: the page's
/// pairing code redeemed over the pinned listener (PairingInvite), the status read and a node's prompt approved through
/// the app's client (DaemonLink, API). That test starts the hub, the node and the prompt and passes them in POINTE_E2E_JOIN_*;
/// without them this skips, so a plain `swift test` never needs a daemon.
final class JoinLiveTests: XCTestCase {
    func testThePhonePairsSeesTheNodesSessionAndApprovesItsPrompt() async throws {
        let env = ProcessInfo.processInfo.environment
        guard let link = env["POINTE_E2E_JOIN_INVITE"], let name = env["POINTE_E2E_JOIN_SESSION"],
              let machine = env["POINTE_E2E_JOIN_MACHINE"], let requestId = env["POINTE_E2E_JOIN_REQUEST"] else {
            throw XCTSkip("run by tests/test_integration_join.py, which starts the hub and the node")
        }
        let invite = try XCTUnwrap(PairingInvite(link: link), "the page's code is one the app reads")
        let (pairing, mac) = try await invite.redeem(device: "Join test iPhone", id: "join-e2e-swift")

        // The pin: the same key with another certificate's fingerprint reaches nothing.
        let other = DaemonLink(Pairing(host: pairing.host, port: pairing.port, fingerprint: String(repeating: "0", count: 64), key: pairing.key))
        do {
            _ = try await API(link: other, session: other.session(onOpen: {})).status()
            XCTFail("a listener whose certificate is not the paired one answered")
        } catch {}

        let daemon = DaemonLink(pairing)
        let api = API(link: daemon, session: daemon.session(onOpen: {}))
        let status = try await api.status()
        XCTAssertNil(daemon.problem(version: status), "the hub and this app speak the same protocol")
        let session = try XCTUnwrap(status.sessions.first { $0.name == name }, "the node's session is in the phone's status")
        XCTAssertEqual(session.machine, machine)
        XCTAssertEqual(session.request_id, requestId)
        XCTAssertTrue(session.waiting && session.canApprove)
        try await api.answer(session, allow: true)
        print("join-e2e: approved \(name) on \(machine) through \(mac)")
    }
}
#endif
