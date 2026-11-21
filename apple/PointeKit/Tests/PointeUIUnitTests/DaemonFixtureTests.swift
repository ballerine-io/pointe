import XCTest
@testable import PointeUI

/// What a daemon really sends decodes: the page rig's busy status, and a status and prefs captured from the daemon's
/// own routes (tests/test_orchestrator.py's client) with the names replaced. A field the daemon renamed fails here.
final class DaemonFixtureTests: XCTestCase {
    private func fixture(_ name: String) throws -> Data {
        let url = try XCTUnwrap(Bundle.module.url(forResource: name, withExtension: "json", subdirectory: "Fixtures"))
        return try Data(contentsOf: url)
    }

    func testABusyStatusDecodesAsThePageRigMakesIt() throws {
        let status = try JSONDecoder().decode(API.Status.self, from: fixture("status-busy"))
        XCTAssertTrue(status.connected)
        XCTAssertEqual(status.sessions.count, 5)
        XCTAssertTrue(status.sessions[1].waiting)
        XCTAssertEqual(status.sessions[1].request, "Bash(rm -rf build && make test)")
        XCTAssertEqual(status.talk?.count, 4)
        XCTAssertEqual(status.ptt?.mode, "always")
        XCTAssertEqual(status.machines?.count, 2)
        let view = MachineView(status)
        XCTAssertEqual(view.names, ["studio", "devbox"])
        XCTAssertEqual(view.onMachine("studio").count, 3)
        XCTAssertEqual(view.onMachine("devbox").count, 2)
    }

    func testTheDaemonsOwnStatusAndPrefsDecode() throws {
        let status = try JSONDecoder().decode(API.Status.self, from: fixture("status-daemon"))
        XCTAssertEqual(status.version, "1.15.0")
        XCTAssertFalse(status.connected)
        XCTAssertTrue(status.sessions.isEmpty)
        XCTAssertEqual(status.machines?.first?.isHere, true)
        XCTAssertEqual(status.keep_awake?.on, false)
        let prefs = try JSONDecoder().decode(API.Prefs.self, from: fixture("prefs-daemon"))
        XCTAssertEqual(prefs.microphone, "always")
        XCTAssertEqual(prefs.patience, "normal")
    }

    func testAnEmptyStatusAndAnOlderDaemonDecode() throws {
        _ = try JSONDecoder().decode(API.Status.self, from: fixture("status-empty"))
        let old = try JSONDecoder().decode(API.Status.self, from: Data(#"{"connected": false, "sessions": []}"#.utf8))
        XCTAssertNil(old.version)
        XCTAssertNil(old.ptt)
        XCTAssertNil(old.machines)
    }
}
