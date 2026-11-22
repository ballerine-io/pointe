import XCTest
@testable import PointeUI

/// The night shift (docs/design/night-shift.md): what the daemon sends decodes, what the app sends is what the daemon
/// reads, and how a refusal reads. The draft's own rules (what Start needs, the body, the ledger's order) are the
/// package's, tested there.
final class NightShiftTests: XCTestCase {
    private func fixture(_ name: String) throws -> Data {
        let url = try XCTUnwrap(Bundle.module.url(forResource: name, withExtension: "json", subdirectory: "Fixtures"))
        return try Data(contentsOf: url)
    }

    func testTheStatusCarriesTheShiftAndItsReadBack() throws {
        let status = try JSONDecoder().decode(API.Status.self, from: fixture("status-night-shift"))
        let shift = try XCTUnwrap(status.night_shift)
        XCTAssertTrue(shift.on)
        XCTAssertEqual(shift.id, "ns-3")
        XCTAssertEqual(shift.statusLine, "1 of 3 done · 1 blocked")
        XCTAssertEqual(shift.budget, 40)
        XCTAssertEqual(shift.hours, 8)
        XCTAssertNil(shift.ended)
        XCTAssertEqual(shift.fronts.map(\.session), ["billing", "shop"])
        XCTAssertEqual(shift.fronts.map(\.state), ["working", "waiting"])
        XCTAssertEqual(status.shift_pending?.id, "sp-1")
        XCTAssertTrue(status.shift_pending?.line.hasSuffix("Start? Say yes or tap.") == true)
    }

    func testAStatusWithoutANightShiftStillDecodes() throws {
        let never = try JSONDecoder().decode(API.Status.self, from: Data(#"{"connected": true, "sessions": [], "night_shift": null, "shift_pending": null}"#.utf8))
        XCTAssertNil(never.night_shift)
        XCTAssertNil(never.shift_pending)
        let old = try JSONDecoder().decode(API.Status.self, from: Data(#"{"connected": true, "sessions": []}"#.utf8))
        XCTAssertNil(old.night_shift, "an older Mac sends neither key")
        XCTAssertNil(old.shift_pending)
        for name in ["status-busy", "status-daemon", "status-empty"] {
            XCTAssertNil(try JSONDecoder().decode(API.Status.self, from: fixture(name)).night_shift, name)
        }
    }

    func testTheShiftDecodesWithItsLedgerAndItsMorning() throws {
        let page = try JSONDecoder().decode(NightShift.Options.self, from: fixture("night-shift"))
        let shift = try XCTUnwrap(page.shift)
        XCTAssertTrue(shift.on)
        XCTAssertEqual(shift.how, "voice")
        XCTAssertEqual(shift.headline, "Six hours in: 1 of 3 tasks done, 1 blocked.")
        XCTAssertEqual(shift.ledger.sections, [.decided, .asked, .done, .blocked, .inFlight])
        XCTAssertEqual(shift.ledger.done.first?.commit, "3f9c2ab")
        XCTAssertEqual(shift.ledger.done.first?.pr, "#128")
        let blocked = try XCTUnwrap(shift.ledger.blocked.first)
        XCTAssertEqual(blocked.request, "Bash: Push the branch\n{\"command\": \"git push origin fix-flaky-test\"}", "word for word, with its line break")
        XCTAssertEqual(blocked.resolved, "approved by you")
        XCTAssertEqual(blocked.waits_on, "you")
        let decided = try XCTUnwrap(shift.ledger.decided.first)
        XCTAssertEqual([decided.question, decided.choice, decided.otherwise],
                       ["Retry three times or five?", "Three, with backoff.", "Five means raising the timeout budget in the config."])
        XCTAssertEqual(shift.ledger.in_flight.first?.task, "add the idempotency test")
        XCTAssertEqual(page.history.map(\.id), ["ns-3", "ns-2"])
        XCTAssertEqual(page.history.last?.why, "complete")
        XCTAssertEqual(page.pending?.id, "sp-1")
        XCTAssertEqual(page.sessions.filter(\.available).map(\.name), ["billing", "docs"])
    }

    func testTheDemoHasEveryScreen() throws {
        XCTAssertNil(try XCTUnwrap(Demo.make(.nightShiftStart)).status.night_shift)
        XCTAssertEqual(try XCTUnwrap(Demo.make(.nightShift)).status.night_shift?.statusLine, "2 of 5 done · 1 blocked")
        XCTAssertEqual(try XCTUnwrap(Demo.make(.nightShiftLedger)).status.sessions.map(\.name), ["billing", "docs", "shop"])
        XCTAssertTrue(try XCTUnwrap(Demo.make(.nightShiftPending)).status.shift_pending?.line.hasPrefix("Night shift. billing:") == true)
        let empty = try XCTUnwrap(Demo.nightShiftPage(on: nil), "the fixture decodes")
        XCTAssertNil(empty.shift)
        XCTAssertTrue(empty.history.isEmpty)
        XCTAssertTrue(NightShift.Draft(empty, starting: Demo.startOptions).canAdd(empty))
        let running = try XCTUnwrap(Demo.nightShiftPage(on: true))
        XCTAssertEqual(running.shift?.ledger.sections, NightShift.Section.allCases, "every part of the ledger shows")
        XCTAssertEqual(running.shift?.summary, Demo.runningShift)
        XCTAssertEqual(running.history.count, 3)
        XCTAssertEqual(Demo.nightShiftPage(on: false)?.shift?.on, false)
        let hebrew: (String) -> Bool = { $0.unicodeScalars.contains { (0x0590...0x05FF).contains($0.value) } }
        for screen in [Demo.Screen.nightShiftStart, .nightShift, .nightShiftLedger, .nightShiftPending] { XCTAssertFalse(hebrew(Demo.source(screen)), "\(screen)") }
    }

    // MARK: what the app sends (the Mac's route: /voice/night-shift)

    private func api(_ status: Int, _ reply: String) -> API {
        HubStub.reply = (status, reply); HubStub.bodies = []; HubStub.urls = []
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [HubStub.self]
        return API(pairing: Demo.pairing, session: URLSession(configuration: config))
    }

    func testTheShiftIsAskedForAndOneFromTheHistoryByItsId() async throws {
        let reply = String(decoding: try fixture("night-shift"), as: UTF8.self)
        let page = try await api(200, reply).nightShift()
        XCTAssertEqual(HubStub.bodies.first?["path"] as? String, "/voice/night-shift")
        XCTAssertNil(HubStub.urls.first?.query)
        XCTAssertEqual(page.shift?.id, "ns-3")
        _ = try await api(200, reply).nightShift(id: "ns-2")
        XCTAssertEqual(HubStub.urls.first?.query, "id=ns-2")
    }

    func testStartPostsTheDraftsBody() async throws {
        let options = try XCTUnwrap(Demo.nightShiftPage(on: nil))
        var draft = NightShift.Draft(options, starting: Demo.startOptions)
        draft.rows[0].task = " finish the retry work and open a PR "
        draft.addRow(options, starting: Demo.startOptions)
        draft.rows[1].starts = true
        draft.rows[1].task = "fix the flaky test"
        draft.notify = true
        try await api(200, #"{"id": "ns-4"}"#).startShift(draft)
        XCTAssertEqual(HubStub.bodies.first?["path"] as? String, "/voice/night-shift")
        let expected: NSDictionary = [
            "action": "start",
            "items": [["session": "billing", "task": "finish the retry work and open a PR"],
                      ["start": ["harness": "claude-code", "folder": "/Users/mira/work/shop"], "task": "fix the flaky test"]],
            "hours": 8, "messages": 40, "notify": true,
        ]
        XCTAssertEqual(HubStub.bodies.first?["body"] as? NSDictionary, expected)
    }

    func testStopAndTheCardsButtonsSendTheirAction() async throws {
        try await api(200, #"{"stopped": true}"#).shiftAction("stop")
        XCTAssertEqual(HubStub.bodies.first?["body"] as? [String: String], ["action": "stop"])
        try await api(200, #"{"id": "ns-4"}"#).shiftAction("confirm", id: "sp-1")
        XCTAssertEqual(HubStub.bodies.first?["body"] as? [String: String], ["action": "confirm", "id": "sp-1"])
        try await api(200, #"{"cancelled": true}"#).shiftAction("cancel", id: "sp-1")
        XCTAssertEqual(HubStub.bodies.first?["body"] as? [String: String], ["action": "cancel", "id": "sp-1"])
    }

    @MainActor
    func testARefusalIsShownInTheMacsOwnWords() async throws {
        let draft = NightShift.Draft(try XCTUnwrap(Demo.nightShiftPage(on: nil)))
        do {
            try await api(409, #"{"detail": "A night shift is already running."}"#).startShift(draft)
            XCTFail("a 409 is a refusal")
        } catch {
            XCTAssertEqual(NightShiftSheet.refusal(error), "A night shift is already running.")
        }
        do {
            try await api(400, #"{"detail": "billing has more than 5 tasks."}"#).startShift(draft)
            XCTFail("a 400 is a refusal")
        } catch {
            XCTAssertEqual(NightShiftSheet.refusal(error), "billing has more than 5 tasks.")
        }
        do { _ = try await api(404, "").nightShift(); XCTFail() } catch {
            XCTAssertEqual(NightShiftSheet.refusal(error), "Pointe on the Mac has no night shift yet: update it.")
        }
        XCTAssertEqual(NightShiftSheet.refusal(URLError(.timedOut)), "The Mac did not answer.")
    }

    @MainActor
    func testTheHoursShowWithoutAPointZero() {
        XCTAssertEqual(NightShiftSheet.count(8), "8")
        XCTAssertEqual(NightShiftSheet.count(7.5), "7.5")
    }

    // MARK: a briefing after a night shift (Briefing.swift)

    func testABriefingCarriesTheNightsLeadAndAnOlderOneHasNone() throws {
        let page = try JSONDecoder().decode(API.BriefingsPage.self, from: Data(#"""
        {"briefings": [{"id": "c3", "at": 1700030000, "since_label": "overnight", "length": "normal", "sections": [], "opener": "",
                        "lead": ["Night shift: 2 of 3 tasks done, 1 blocked.", "billing chose three retries, with backoff."], "night": "ns-3",
                        "scheduled": true, "empty": false},
                       {"id": "b7", "at": 1699900000, "since_label": "today", "length": "short", "sections": [], "opener": "Quiet today.",
                        "scheduled": false, "empty": true}]}
        """#.utf8))
        XCTAssertEqual(page.briefings?.first?.lead, ["Night shift: 2 of 3 tasks done, 1 blocked.", "billing chose three retries, with backoff."])
        XCTAssertEqual(page.briefings?.first?.opener, "")
        XCTAssertNil(page.briefings?.last?.lead)
        XCTAssertEqual(page.briefings?.last?.opener, "Quiet today.")
    }
}
