import UserNotifications
import XCTest
@testable import PointeUI

/// "<agent> replied": posted once like any alert, and a tap on it opens that agent's replies.
final class AgentReplyTests: XCTestCase {
    private let replied = """
    [{"id": "agent_reply:hermes:0", "kind": "agent_reply", "session": "hermes", "title": "hermes replied",
      "body": "Open Pointe to read it.", "text": "Open Pointe to read it.", "approvable": false, "at": 1000, "quiet": false}]
    """

    private func plan(_ json: String, posted: Set<String> = []) -> AlertPlan.Result {
        AlertPlan.plan(try! JSONDecoder().decode([API.Attention].self, from: Data(json.utf8)), posted: posted, delivered: [],
                       appActive: false, enabled: true, watchApprove: true)
    }

    func testAReplyIsOneNotificationWithNoActionsThatNamesTheAgent() {
        let r = plan(replied)
        XCTAssertEqual(r.post.count, 1)
        let n = r.post[0]
        XCTAssertEqual(n.title, "hermes replied")
        XCTAssertEqual(n.body, "Open Pointe to read it.", "exactly the Mac's body: never the agent's words")
        XCTAssertEqual(n.category, AlertPlan.openCategory)
        XCTAssertEqual(n.kind, "agent_reply")
        XCTAssertEqual(n.session, "hermes")
        XCTAssertEqual(plan(replied, posted: r.posted).post, [], "more replies under the same id: not posted again")
    }

    func testATapOnItOpensThatAgentsReplies() {
        let info: [AnyHashable: Any] = ["kind": "agent_reply", "session": "hermes"]
        XCTAssertEqual(AlertOpen.agentReply(action: UNNotificationDefaultActionIdentifier, userInfo: info), "hermes")
        XCTAssertNil(AlertOpen.agentReply(action: UNNotificationDismissActionIdentifier, userInfo: info), "swiped away: nothing opens")
        XCTAssertNil(AlertOpen.agentReply(action: AlertAnswer.deny, userInfo: info))
        XCTAssertNil(AlertOpen.agentReply(action: UNNotificationDefaultActionIdentifier,
                                          userInfo: ["kind": "question", "session": "hermes"]), "another alert only opens the app")
        XCTAssertNil(AlertOpen.agentReply(action: UNNotificationDefaultActionIdentifier, userInfo: ["kind": "agent_reply"]))
    }

    func testTheRepliesDecodeAndTheSheetSaysWhoReplied() throws {
        let r = try JSONDecoder().decode(API.AgentReplies.self, from: Data("""
        {"agent": "hermes", "replies": [{"text": "Friday is clear.", "at": "2026-11-27T07:00:00Z"}, {"text": "And Monday."}]}
        """.utf8))
        XCTAssertEqual(r.agent, "hermes")
        XCTAssertEqual(r.replies.map(\.text), ["Friday is clear.", "And Monday."])
        XCTAssertNil(r.replies[1].at)
        XCTAssertEqual(AgentReplyCopy.title("hermes"), "hermes replied")
    }

    @MainActor func testTheCallScreenOpensWhatATapAskedFor() throws {
        XCTAssertTrue(try Repo.source("Alerts.swift").contains("AgentReplyOpener.shared.agent = AgentName(id: reply)"))
        XCTAssertTrue(try Repo.source("CallView.swift").contains(".background(AgentReplyPresenter(load: agentReplies))"))
        AgentReplyOpener.shared.agent = AgentName(id: "hermes")
        XCTAssertEqual(AgentReplyOpener.shared.agent?.id, "hermes")
        AgentReplyOpener.shared.agent = nil
    }
}
