import SwiftUI

/// Thinking and working (docs/features/thinking.md) and the progress updates (docs/features/progress.md). The Mac's
/// status says what is true on the call while nothing is being said (`phase`): "thinking" from the moment the owner's
/// turn is taken until the reply is heard or shown, "working" while a session has their request. The state line shows it
/// where it said "Listening" (CallTitle), after Speaking… and Writing…. The call's own link says "thinking" the moment
/// the turn is taken ({"type": "phase"}), so the line does not wait for the next status.
extension API {
    struct Phase: Decodable, Equatable {
        let name: String            // "thinking" or "working"
        var session: String? = nil  // working: the session that has the request

        private enum CodingKeys: String, CodingKey { case name, session }
    }
}

/// The page's words (ui_thinking.html), word for word.
enum ThinkingCopy {
    static let thinking = "Thinking…"
    static func working(_ session: String) -> String { "\(session) is working…" }
    static let cue = "Waiting sound"
    static let cueHint = "A soft sound when Pointe needs more than a moment to answer."
    static let progress = "Progress updates"
    static let progressHint = "While a session works on your request, Pointe says one short line after 20 seconds, then every 45."
    static let section = "While you wait"
    static let failed = "The Mac did not take the setting. Is Pointe on the Mac up to date?"

    static func isWorking(_ title: String) -> Bool { title.hasSuffix(working("")) }
}

enum ThinkingRule {
    /// What the call's own link said, and when.
    struct Told: Equatable {
        let phase: API.Phase
        let at: Date
    }

    /// How long the link's word stands in for a status that has not said it yet: a status already on its way when the
    /// turn was taken is older than the link's word. Past this, a turn the status never called thinking got no reply.
    static let holdSecs: TimeInterval = 0.9

    /// The Mac's {"type": "phase", "name": …, "session": …}; nil for any other message.
    static func message(_ message: [String: Any]) -> API.Phase? {
        guard message["type"] as? String == "phase", let name = message["name"] as? String else { return nil }
        return API.Phase(name: name, session: message["session"] as? String)
    }

    /// What to show: the status once it says a phase, else the link's word while it is fresh.
    static func phase(status: API.Status?, told: Told?, now: Date = Date()) -> API.Phase? {
        guard let status, status.connected else { return nil }
        if let phase = status.phase { return phase }
        guard let told, now.timeIntervalSince(told.at) < holdSecs, now >= told.at else { return nil }
        return told.phase
    }
}

/// The state line's dot. Green is the owner's turn or a session's work, orange is Pointe's turn; the motion tells the
/// states apart without colour: still while it listens, a breath while it speaks or a session works, a shrink to a
/// loader while it thinks. Reduce Motion stops it; the words carry the state.
struct StateDot: View {
    enum Motion: Equatable { case none, breathe, shrink }
    enum Kind: Equatable {
        case steady, speaking, thinking, working

        var pointesTurn: Bool { self == .speaking || self == .thinking }
        var motion: Motion {
            switch self {
            case .steady: .none
            case .speaking, .working: .breathe
            case .thinking: .shrink
            }
        }
    }

    /// From the line's own words, so the dot can never disagree with them. `speaking`: Pointe speaks, or writes.
    static func kind(title: String, speaking: Bool) -> Kind {
        if speaking { return .speaking }
        if title == ThinkingCopy.thinking { return .thinking }
        return ThinkingCopy.isWorking(title) ? .working : .steady
    }

    static func moves(_ kind: Kind, reduceMotion: Bool) -> Bool { !PointeUI.Motion.reduced(reduceMotion) && kind.motion != .none }

    let kind: Kind
    let tint: Color
    var size: CGFloat = 8
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var low = false

    var body: some View {
        let moving = Self.moves(kind, reduceMotion: reduceMotion)
        Circle().fill(tint).frame(width: size, height: size)
            .scaleEffect(moving && low && kind.motion == .shrink ? 0.45 : 1)
            .opacity(moving && low ? (kind.motion == .shrink ? 0.6 : 0.35) : 1)
            .motion(moving ? PointeUI.Motion.breathing(kind == .working ? 0.8 : 0.6) : .default, value: low)
            .onAppear { low = moving }
            .onChange(of: moving) { _, now in low = now }
            .id(kind)  // a new state starts its own motion from rest
    }
}
