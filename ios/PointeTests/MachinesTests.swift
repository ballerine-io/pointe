import XCTest
@testable import Pointe

/// Multi-machine (docs/design/multi-machine.md, "iPhone app"): which machine runs each session, the filter, the labels,
/// offline, the invite line and the notification title, on the status fields the design defines.
final class MachinesTests: XCTestCase {
    private func status(_ json: String) -> API.Status {
        try! JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    private let now = 1_794_400_000.0

    private var three: API.Status {
        status("""
        {"connected": true, "mode": "orchestrator",
         "sessions": [{"name": "billing/main", "working": true, "waiting": false, "machine": "", "online": true},
                      {"name": "shop", "working": false, "waiting": false},
                      {"name": "shop devbox", "working": true, "waiting": true, "request_id": "r1", "machine": "devbox", "online": true},
                      {"name": "api", "working": false, "waiting": false, "needs": "a budget", "machine": "devbox", "online": true},
                      {"name": "notes", "working": false, "waiting": true, "request_id": "r2", "machine": "laptop", "online": false}],
         "machines": [{"id": "hub", "name": "studio", "here": true, "os": "macos", "online": true, "sessions": 2, "need": 0},
                      {"id": "n3f2a1", "name": "devbox", "here": false, "os": "linux", "online": true, "sessions": 2, "need": 2,
                       "rtt_ms": 23, "key_fp": "3f2a9c41d07be215"},
                      {"id": "n91c0de", "name": "laptop", "here": false, "os": "macos", "online": false, "since": \(now - 1800),
                       "sessions": 1, "need": 0}],
         "invite": {"code": "K7PQ-2MXD", "expires_in": 540}}
        """)
    }

    func testTheDesignsStatusFieldsDecode() {
        let s = three
        XCTAssertEqual(s.machines?.count, 3)
        XCTAssertEqual(s.machines?[1].rtt_ms, 23)
        XCTAssertEqual(s.machines?[1].key_fp, "3f2a9c41d07be215")
        XCTAssertEqual(s.machines?[2].isOffline, true)
        XCTAssertEqual(s.invite, API.Invite(code: "K7PQ-2MXD", expires_in: 540, link: nil))
        XCTAssertEqual(s.sessions[2].machine, "devbox")
        XCTAssertTrue(s.sessions[4].isOffline)
        XCTAssertNil(s.sessions[1].machine, "a session from this Mac may carry no machine")
    }

    func testAnOlderMacWithoutMachinesLooksAsBefore() {
        let s = status(#"{"connected": true, "sessions": [{"name": "docs", "working": false, "waiting": false}]}"#)
        XCTAssertNil(s.machines)
        XCTAssertNil(s.invite)
        let v = MachineView(s)
        XCTAssertFalse(v.multi)
        XCTAssertFalse(v.mixed)
        XCTAssertEqual(v.label(s.sessions[0]), "docs")
        XCTAssertEqual(v.shown("devbox").map(\.name), ["docs"], "no filter without machines")
    }

    func testOneMachineShowsNoGroupsChipsOrTags() {
        let s = status("""
        {"connected": true, "sessions": [{"name": "docs", "working": false, "waiting": false, "machine": ""}],
         "machines": [{"id": "hub", "name": "studio", "here": true, "os": "macos", "online": true, "sessions": 1}]}
        """)
        let v = MachineView(s)
        XCTAssertFalse(v.multi)
        XCTAssertFalse(v.mixed)
        XCTAssertEqual(v.label(s.sessions[0]), "docs")
    }

    func testThisMacComesFirstThenEachMachine() {
        let v = MachineView(three)
        XCTAssertEqual(v.names, ["studio", "devbox", "laptop"])
        XCTAssertTrue(v.multi)
        XCTAssertTrue(v.mixed)
        XCTAssertEqual(v.of(three.sessions[1]), "studio", "no machine is this Mac")
    }

    func testTheFilterIsAViewOfOneMachineAndFallsBackToAll() {
        let v = MachineView(three)
        XCTAssertEqual(v.shown(nil).count, 5)
        XCTAssertEqual(v.shown("devbox").map(\.name), ["shop devbox", "api"])
        XCTAssertEqual(v.valid("gone"), nil, "a revoked machine's filter falls back to All")
        XCTAssertEqual(v.shown("gone").count, 5)
    }

    func testCardsAndNotificationsSayShopDotDevbox() {
        let v = MachineView(three)
        XCTAssertEqual(v.label(three.sessions[2]), "shop · devbox", "the machine suffix is dropped for the label")
        XCTAssertEqual(v.label(three.sessions[1]), "shop · studio", "mixed: this Mac's sessions say so too")
        XCTAssertEqual(v.label(three.sessions[3]), "api · devbox")
    }

    func testAMachineHeaderSaysOSRoundTripOrOfflineSince() {
        let v = MachineView(three)
        XCTAssertEqual(v.header("studio"), "studio · this Mac")
        XCTAssertEqual(v.header("devbox"), "devbox · Linux · 23 ms")
        XCTAssertEqual(v.header("laptop", now: Date(timeIntervalSince1970: now)),
                       "laptop · macOS · offline since \(MachinesCopy.since(now - 1800, now: Date(timeIntervalSince1970: now)))")
        XCTAssertTrue(v.isOffline("laptop"))
    }

    func testOfflineSinceIsAClockTimeTodayAndADayBefore() {
        let today = Date(timeIntervalSince1970: now)
        XCTAssertTrue(MachinesCopy.since(now - 60, now: today).range(of: #"^\d\d:\d\d$"#, options: .regularExpression) != nil)
        XCTAssertTrue(MachinesCopy.since(now - 3 * 86_400, now: today).range(of: #"^[A-Z][a-z]{2} \d\d:\d\d$"#, options: .regularExpression) != nil)
        XCTAssertEqual(MachinesCopy.since(nil), "a while")
    }

    func testTheCodeCountsDownFromTenMinutes() {
        XCTAssertEqual(MachinesCopy.countdown(600), "10:00")
        XCTAssertEqual(MachinesCopy.countdown(539.4), "8:59")
        XCTAssertEqual(MachinesCopy.countdown(9), "0:09")
        XCTAssertNil(MachinesCopy.countdown(0.4), "a lapsed code is not shown")
    }

    func testTheJoinLineCarriesWhatThisPhonePairedWith() {
        let pairing = Pairing(host: "studio.example.ts.net", port: 7443, fingerprint: "3b1c", key: "secret-key")
        let line = MachinesCopy.joinLine(API.Invite(code: "K7PQ-2MXD", expires_in: 600, link: nil), pairing: pairing)
        XCTAssertEqual(line, "pointe node join 'pointe://hub?v=1&host=studio.example.ts.net&port=7443&fp=3b1c&code=K7PQ-2MXD'")
        XCTAssertFalse(line.contains("secret-key"), "never the phone's own key")
        let given = API.Invite(code: "K7PQ-2MXD", expires_in: 600, link: "pointe://hub?v=1&host=h&port=1&fp=f&code=K7PQ-2MXD")
        XCTAssertEqual(MachinesCopy.joinLine(given, pairing: pairing), "pointe node join 'pointe://hub?v=1&host=h&port=1&fp=f&code=K7PQ-2MXD'")
    }

    private func attention(_ session: String, _ id: String) -> API.Attention {
        try! JSONDecoder().decode(API.Attention.self, from: Data("""
        {"id": "permission:\(id)", "kind": "permission", "session": "\(session)", "request_id": "\(id)",
         "title": "\(session) needs approval", "body": "run the tests", "approvable": true}
        """.utf8))
    }

    func testANotificationKeepsTheMacsTitle() {  // alerts.py names the machine; the app does not name it twice
        let n = AlertPlan.note(attention("shop devbox", "r1"), watchApprove: true, machines: MachineView(three))
        XCTAssertEqual(n?.title, "shop devbox needs approval")
        XCTAssertEqual(n?.category, AlertPlan.approveCategory)
        XCTAssertEqual(n?.session, "shop devbox", "the answer still goes to the session by its real name")
    }

    func testAnOfflineSessionsNotificationHasNoApproveOrDeny() {
        let n = AlertPlan.note(attention("notes", "r2"), watchApprove: true, machines: MachineView(three))
        XCTAssertEqual(n?.category, AlertPlan.openCategory)
        XCTAssertNil(n?.requestId)
    }

    func testOneMachineNotificationsAreUnchanged() {
        let n = AlertPlan.note(attention("river-lantern", "a1"), watchApprove: true)
        XCTAssertEqual(n?.title, "river-lantern needs approval")
    }

    func testEveryMultiMachineDemoScreenDecodes() {
        for screen in [Demo.Screen.machines, .machinesOne, .machinesOffline] {
            XCTAssertNoThrow(try JSONDecoder().decode(API.Status.self, from: Data(Demo.machinesJSON(screen).utf8)), "\(screen)")
        }
    }
}
