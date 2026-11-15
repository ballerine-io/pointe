import XCTest
@testable import Pointe

/// Feature 7: which notifications the app posts and withdraws from a status poll, and what an action on one does.
final class AlertsTests: XCTestCase {
    private func attention(_ json: String) -> [API.Attention] {
        try! JSONDecoder().decode([API.Attention].self, from: Data(json.utf8))
    }

    private let readable = """
    [{"id": "permission:a1b2c3d4", "kind": "permission", "session": "river-lantern", "request_id": "a1b2c3d4",
      "title": "river-lantern needs approval", "body": "run: git push origin dev", "text": "run: git push origin dev",
      "approvable": true, "at": 1000}]
    """
    private let unreadable = """
    [{"id": "permission:c0ffee01", "kind": "permission", "session": "river-lantern", "request_id": "c0ffee01",
      "title": "river-lantern needs approval", "body": "Bash: open Pointe to see the exact request", "approvable": false}]
    """

    private func plan(_ items: [API.Attention], posted: Set<String> = [], delivered: Set<String> = [], active: Bool = false,
                      enabled: Bool = true, watch: Bool = true) -> AlertPlan.Result {
        AlertPlan.plan(items, posted: posted, delivered: delivered, appActive: active, enabled: enabled, watchApprove: watch)
    }

    func testAReadableRequestInTheBackgroundIsOneNotificationWithApproveBoundToItsId() {
        let r = plan(attention(readable))
        XCTAssertEqual(r.post.count, 1)
        let n = r.post[0]
        XCTAssertEqual(n.id, "permission:a1b2c3d4")
        XCTAssertEqual(n.title, "river-lantern needs approval")
        XCTAssertEqual(n.body, "run: git push origin dev", "exactly the Mac's body: what Approve answers")
        XCTAssertEqual(n.category, AlertPlan.approveCategory)
        XCTAssertEqual(n.session, "river-lantern")
        XCTAssertEqual(n.requestId, "a1b2c3d4")
        XCTAssertEqual(r.posted, [AlertPlan.key(n)])
        XCTAssertEqual(plan(attention(readable), posted: r.posted).post, [], "never posted twice")
        XCTAssertEqual(plan(attention(readable), posted: r.posted, watch: false).post, [],
                       "a later poll that did not read the setting does not post it again with fewer actions")
        XCTAssertEqual(plan(attention(readable), posted: ["permission:a1b2c3d4"]).post, [], "an older build's entry counts")
    }

    func testAfterAnActionTheLastGoodStatusIsKeptWhenTheFetchFails() throws {
        let source = try String(contentsOf: URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Pointe/CallView.swift"), encoding: .utf8)
        XCTAssertFalse(source.contains("status = try? await"), "a failed fetch would blank the Machines list")
        XCTAssertTrue(source.contains("if let fresh = try? await call.api.status() { status = fresh }"))
    }

    func testWithoutTheSettingOrForAnUnreadableRequestThereIsNoApprove() {
        XCTAssertEqual(plan(attention(readable), watch: false).post.first?.category, AlertPlan.denyCategory)
        XCTAssertEqual(plan(attention(unreadable)).post.first?.category, AlertPlan.denyCategory)
    }

    func testWhileTheAppIsOnScreenTheCardIsEnoughAndTheItemWaitsForTheBackground() {
        let r = plan(attention(readable), active: true)
        XCTAssertEqual(r.post, [])
        XCTAssertEqual(r.posted, [])
        XCTAssertEqual(plan(attention(readable), posted: r.posted).post.count, 1, "posted once the app leaves the screen")
    }

    func testWhileTheUserIsAtTheMacNothingIsPostedAndItIsPostedOnceTheyLeave() {
        let quiet = attention(readable.replacingOccurrences(of: #""approvable": true"#, with: #""approvable": true, "quiet": true"#))
        XCTAssertEqual(quiet[0].quiet, true)
        let r = plan(quiet)
        XCTAssertEqual(r.post, [])
        XCTAssertEqual(r.posted, [], "not recorded as posted: it is still to come")
        XCTAssertEqual(r.withdraw, [])
        let later = plan(attention(readable), posted: r.posted)  // the Mac idle for a minute, or the approval near its timeout
        XCTAssertEqual(later.post.map(\.id), ["permission:a1b2c3d4"])
        XCTAssertNil(attention(readable)[0].quiet, "an older Mac sends none: posted as before")
    }

    func testAnAlreadyPostedItemIsNotWithdrawnWhenTheUserSitsDown() {
        let r = plan(attention(readable))
        let quiet = attention(readable.replacingOccurrences(of: #""approvable": true"#, with: #""approvable": true, "quiet": true"#))
        let then = plan(quiet, posted: r.posted, delivered: ["permission:a1b2c3d4"])
        XCTAssertEqual(then.withdraw, [])
        XCTAssertEqual(then.posted, r.posted)
    }

    func testAnsweredElsewhereIsWithdrawn() {
        let r = plan([], posted: ["permission:a1b2c3d4"], delivered: ["permission:a1b2c3d4", "hand:m1:2"])
        XCTAssertEqual(r.withdraw, ["hand:m1:2", "permission:a1b2c3d4"])
        XCTAssertEqual(r.posted, [])
    }

    func testAMacWithoutSafeBodiesGetsNoNotificationsAtAll() {
        let old = attention("""
        [{"id": "permission:p1", "kind": "permission", "session": "pricing", "text": "Bash: tidy\\nrm -rf build"}]
        """)
        XCTAssertEqual(plan(old).post, [], "an older Mac sends the full text: it never reaches a lock screen")
    }

    func testTurnedOffPostsNothingAndWithdrawsWhatIsShown() {
        let r = plan(attention(readable), posted: ["permission:a1b2c3d4"], delivered: ["permission:a1b2c3d4"], enabled: false)
        XCTAssertEqual(r.post, [])
        XCTAssertEqual(r.withdraw, ["permission:a1b2c3d4"])
    }

    func testAQuestionOrAHandOnlyOpensTheApp() {
        let items = attention("""
        [{"id": "question:docs:1000", "kind": "question", "session": "docs", "title": "docs needs you",
          "body": "a decision on the retry budget", "approvable": false},
         {"id": "hand:m1:1", "kind": "hand", "title": "Pointe wants to speak", "body": "The p95 is 300 ms",
          "text": "The p95 is 300 ms", "approvable": false, "at": 1000},
         {"id": "hand:m0:1", "kind": "hand", "text": "from an older Mac", "at": 900}]
        """)
        let r = plan(items)
        XCTAssertEqual(r.post.map(\.category), [AlertPlan.openCategory, AlertPlan.openCategory])
        XCTAssertEqual(r.post[1].title, "Pointe wants to speak")
        XCTAssertNil(r.post[0].requestId)
        XCTAssertFalse(r.post.contains { $0.id == "hand:m0:1" }, "no title and body from the Mac: nothing posted")
    }

    // MARK: actions

    func testApproveAndDenyCarryTheirSessionAndRequestId() {
        let info: [AnyHashable: Any] = ["session": "river-lantern", "request_id": "a1b2c3d4"]
        XCTAssertEqual(AlertAnswer.decision(action: AlertAnswer.approve, userInfo: info),
                       .init(session: "river-lantern", requestId: "a1b2c3d4", allow: true))
        XCTAssertEqual(AlertAnswer.decision(action: AlertAnswer.deny, userInfo: info)?.allow, false)
        XCTAssertNil(AlertAnswer.decision(action: "com.apple.UNNotificationDefaultActionIdentifier", userInfo: info),
                     "a tap on the notification opens the app; it answers nothing")
        XCTAssertNil(AlertAnswer.decision(action: AlertAnswer.approve, userInfo: ["session": "river-lantern"]))
    }

    func testWhatTheUserIsToldAfterAnAction() {
        XCTAssertNil(AlertAnswer.outcome(nil))
        XCTAssertEqual(AlertAnswer.outcome(API.Failure.status(409, "that request is no longer pending")), AlertCopy.alreadyAnswered)
        XCTAssertEqual(AlertAnswer.outcome(API.Failure.status(403, "approve this one in the app or on the page")), AlertCopy.approveInApp)
        XCTAssertEqual(AlertAnswer.outcome(URLError(.timedOut)), AlertCopy.unreachable)
        XCTAssertEqual(AlertAnswer.outcome(API.Failure.status(502, "the answer did not reach the session")), AlertCopy.unreachable)
    }

    func testTheSettingDecodesFromPrefsAndDefaultsOff() throws {
        let off = try JSONDecoder().decode(API.Prefs.self, from: Data("{}".utf8))
        XCTAssertFalse(off.watchApprove)
        let on = try JSONDecoder().decode(API.Prefs.self, from: Data(#"{"alerts.watch_approve": true}"#.utf8))
        XCTAssertTrue(on.watchApprove)
    }
}
