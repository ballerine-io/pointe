import XCTest
@testable import PointeUI

/// Permissions for new sessions (docs/features/new-session.md): the Mac's setting "sessions.permissions", one row in
/// Settings on the iPhone and the Mac, and the risk line under a start the first time it skips prompts. The words are the
/// daemon's and the page's.
final class NewSessionPermissionsTests: XCTestCase {
    private func prefs(_ json: String) throws -> API.Prefs {
        try JSONDecoder().decode(API.Prefs.self, from: Data(json.utf8))
    }

    private func model(_ prefs: API.Prefs?) -> CallSettingsModel {
        CallSettingsModel(status: nil, prefs: prefs, microphone: "always", talkStyle: .hold, live: true, dumping: false,
                          driving: false, driveSuggest: false, demo: false)
    }

    func testTheRowShowsTheMacsValueAndIsHiddenForAMacWithoutIt() throws {
        XCTAssertEqual(model(try prefs(#"{"sessions.permissions": "skip"}"#)).newSessionPermissions, "skip")
        XCTAssertEqual(model(try prefs(#"{"sessions.permissions": "ask"}"#)).newSessionPermissions, "ask")
        XCTAssertNil(model(try prefs(#"{"microphone": "always"}"#)).newSessionPermissions, "a Mac from before the setting: no row")
        XCTAssertNil(model(try prefs(#"{"sessions.permissions": "bypass"}"#)).newSessionPermissions, "only the two values")
    }

    func testTheKeyAndTheWordsAreTheDaemonsAndThePages() throws {
        let prefsSource = try Repo.text("pointe/prefs.py"), daemon = try Repo.text("pointe/newsession.py")
        let page = try Repo.text("pointe/ui.html"), view = try Repo.source("CallView.swift")
        XCTAssertTrue(prefsSource.contains("\"sessions.permissions\": (\"skip\", (\"skip\", \"ask\"))"), "skip is the default")
        XCTAssertTrue(view.contains("\"sessions.permissions\": value"))
        XCTAssertTrue(daemon.contains("(\"skip\", \"\(NewSessionCopy.permissionsSkip)\")"))
        XCTAssertTrue(daemon.contains("(\"ask\", \"\(NewSessionCopy.permissionsAsk)\")"))
        XCTAssertTrue(daemon.contains("PERMISSIONS_SETTING = \"\(NewSessionCopy.permissionsSetting)\""))
        XCTAssertTrue(page.contains("permissionsSkip: '\(NewSessionCopy.permissionsSkip)'"))
    }

    func testAStartThatSkipsShowsTheRiskOnceAndAFailureStillShowsWhy() {
        let first = NewSession.Starting(id: "a", name: "shop-2", state: "waiting", notice: NewSessionCopy.skipNotice)
        XCTAssertEqual(first.why, NewSessionCopy.skipNotice)
        XCTAssertNil(NewSession.Starting(id: "b", name: "shop-3", state: "waiting", notice: "").why)
        let failed = NewSession.Starting(id: "c", name: "shop-4", state: "failed", detail: "Codex is not installed.", notice: "x")
        XCTAssertEqual(failed.why, "Codex is not installed.")
    }

    func testTheStatusRowDecodesTheNotice() throws {
        let row = try JSONDecoder().decode(NewSession.Starting.self, from: Data(#"{"id": "a", "name": "shop-2", "state": "starting", "notice": "Say it once."}"#.utf8))
        XCTAssertEqual(row.why, "Say it once.")
    }
}
