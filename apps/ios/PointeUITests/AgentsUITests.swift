import XCTest

/// Settings → Agents (docs/design/agents.md), on the -demo fixtures: no Mac and no agent needed. The list shows each
/// agent with whether it answers, Connect an agent opens its form with Connect off until it is filled, and Remove asks
/// first. Screenshots go to PARITY_SHOTS (the ui workflow's parity folder).
@MainActor
final class AgentsUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func launch(dark: Bool = false) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", "call", "-demoEnglish", "-pointe.theme", dark ? "dark" : "light", "-sheet", "agents"]
        app.launch()
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["PARITY_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    private func any(_ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    func testTheListShowsEachAgentAndConnectIsOffUntilFilled() {
        for dark in [false, true] {
            launch(dark: dark)
            XCTAssertTrue(any("agent.juniper").waitForExistence(timeout: 15), "the demo's agents are listed")
            XCTAssertTrue(any("agent.hermes").exists)
            XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "offline: hermes is not reachable")).firstMatch.exists,
                          "an agent that does not answer says so")
            shot("iphone-agents-\(dark ? "dark" : "light")")
            any("agentAdd").tap()
            let connect = app.buttons.matching(identifier: "agentConnect").firstMatch  // the button, not its toolbar container
            XCTAssertTrue(connect.waitForExistence(timeout: 10), "the form opens")
            XCTAssertFalse(connect.isEnabled, "nothing to connect until address and token are filled")
            shot("iphone-agents-add-\(dark ? "dark" : "light")")
            app.terminate()
        }
    }

    func testATapOnAReplyNotificationOpensTheAgentsReplies() {
        for dark in [false, true] {
            app = XCUIApplication()
            app.launchArguments = ["-demo", "call", "-demoEnglish", "-pointe.theme", dark ? "dark" : "light", "-sheet", "agentReply"]
            app.launch()
            XCTAssertTrue(app.navigationBars["hermes replied"].waitForExistence(timeout: 15), "the sheet names the agent")
            XCTAssertEqual(app.staticTexts.matching(identifier: "agentReplyText").count, 2, "each reply, as the Mac sent it")
            shot("iphone-agent-reply-\(dark ? "dark" : "light")")
            app.terminate()
        }
    }

    func testRemoveAsksFirst() {
        launch()
        XCTAssertTrue(any("agentRemove.hermes").waitForExistence(timeout: 15))
        any("agentRemove.hermes").tap()
        XCTAssertTrue(any("agentRemoveConfirm").waitForExistence(timeout: 10), "Remove asks before it removes")
    }
}
