import Observation
import SwiftUI
import UserNotifications

// "<agent> replied" (docs/design/agents.md): an agent answered while no call was up. The notification names the agent
// and nothing more (alerts.py); a tap on it opens its replies here, and reading them counts as hearing them on the Mac.

extension API {
    struct AgentReplies: Decodable, Equatable {
        let agent: String
        let replies: [AgentReply]
    }

    struct AgentReply: Decodable, Equatable {
        let text: String
        var at: String? = nil
    }

}

enum AgentReplyCopy {
    static func title(_ name: String) -> String { "\(name) replied" }
    static let reading = "Reading the reply…"
    static let none = "No reply waits."
    static let unreachable = "The Mac did not answer. Try again in a moment."
}

/// Which tap opens an agent's replies. Pure, so it is tested without a notification center.
enum AlertOpen {
    static let agentReplyKind = "agent_reply"

    /// The agent whose replies a tap on "<agent> replied" opens; nil for an action or any other notification.
    static func agentReply(action: String, userInfo: [AnyHashable: Any]) -> String? {
        guard action == UNNotificationDefaultActionIdentifier, userInfo["kind"] as? String == agentReplyKind,
              let session = userInfo["session"] as? String, !session.isEmpty else { return nil }
        return session
    }
}

struct AgentName: Identifiable, Equatable { let id: String }

/// The agent a tap asked for: set by AlertCenter, which may run before any screen is up, and shown by the call screen.
@MainActor @Observable
final class AgentReplyOpener {
    static let shared = AgentReplyOpener()
    var agent: AgentName?
}

extension Demo {
    /// A made-up reply, nothing sent: for screenshots and UI tests (`-sheet agentReply`).
    static func agentReplies(_ name: String) async throws -> API.AgentReplies {
        API.AgentReplies(agent: name, replies: [
            API.AgentReply(text: "Friday is clear until 2 pm. Your dentist appointment moved to Monday at 9."),
            API.AgentReply(text: "The flight to Lisbon is on time and the hotel confirmed late check-in."),
        ])
    }
}

/// Sits behind the call screen and opens the replies a notification asked for.
struct AgentReplyPresenter: View {
    let load: ((String) async throws -> API.AgentReplies)?

    var body: some View {
        @Bindable var opener = AgentReplyOpener.shared
        Color.clear.sheet(item: $opener.agent) { a in
            AgentReplySheet(name: a.id, load: load).presentationDetents([.large]).sheetSurface()
        }
    }
}

struct AgentReplySheet: View {
    let name: String
    let load: ((String) async throws -> API.AgentReplies)?
    @State private var replies: [API.AgentReply]?
    @State private var problem: String?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            BrandForm {
                Section {
                    if let replies, !replies.isEmpty {
                        ForEach(Array(replies.enumerated()), id: \.offset) { _, r in
                            Text(r.text).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                                .readingDirection(of: r.text)
                                .accessibilityIdentifier("agentReplyText")
                        }
                    } else if replies != nil {
                        Text(AgentReplyCopy.none).foregroundStyle(Brand.muted).accessibilityIdentifier("agentReplyNone")
                    } else if let problem {
                        Text(problem).foregroundStyle(Brand.accent).accessibilityIdentifier("agentReplyProblem")
                    } else {
                        Text(AgentReplyCopy.reading).foregroundStyle(Brand.muted)
                    }
                }
            }
            .scrollContentBackground(.hidden)
            .sheetTitle(AgentReplyCopy.title(name))
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .task {
                guard let load else { replies = []; return }
                do { replies = try await load(name).replies } catch { problem = AgentReplyCopy.unreachable }
            }
        }
    }
}
