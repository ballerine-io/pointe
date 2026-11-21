import Foundation

/// Word for word the page's copy (ui.html DUMP_COPY) and the daemon's (braindump.COPY): the three must not drift
/// (tests/test_brain_dump.py).
public enum BrainDumpCopy {
    public static let button = "Brain dump"
    public static let done = "Done"
    public static let title = "Brain dump"
    public static let lede = "Talk freely. Nothing is sent until you say so."
    public static let empty = "Start talking. Every thought lands here."
    public static let hint = "When you're done: tap Done, or say “done” or “over to you”."
    public static let structuring = "Structuring your thoughts…"
    public static let reviewTitle = "Your brain dump, structured"
    public static let reviewLede = "In your words. Edit it, add more, or send it."
    public static let reviewHint = "Or say “send it to …”, “add more”, “read it back” or “discard”."
    public static let addMore = "Add more"
    public static let discard = "Discard"
    public static let discardSure = "Discard the dump?"
    public static let to = "To:"
    public static let send = "Send"
    public static let sendSure = "Tap again to send"
    public static let sendTo = "Send to"
    public static let sent = "Sent to"
    public static let orchestrator = "Orchestrator"
    public static let gone = "is gone, so this goes to the orchestrator."
    public static let readBack = "Read it back"
    public static let fallback = "Pointe could not structure it; this is what you said."
    public static let resumed = "Still here from earlier."
    public static let state = "Brain dump"
    public static let review = "Review"

    /// The dock button's word: start, done, or open the review.
    public static func buttonLabel(_ dump: API.BrainDump?) -> String {
        guard let dump else { return button }
        return dump.isDumping ? done : review
    }

    /// Where the send goes: the one picked here, else where the Mac says (the routing when the dump started). A Mac
    /// before 1.7 sends no `send_to` and cannot take the orchestrator: there, the session named by voice, else the active one.
    public static func target(_ dump: API.BrainDump, picked: DumpTarget?, active: String?, sessions: [String]) -> DumpTarget? {
        let offered = choices(dump, sessions: sessions)
        if let picked, offered.contains(picked) { return picked }
        guard let to = dump.send_to else {
            return ([dump.target, active].compactMap { $0 }.first { sessions.contains($0) } ?? sessions.first).map { .session($0) }
        }
        if !to.orchestrator, let name = to.session, sessions.contains(name) { return .session(name) }
        return .orchestrator
    }

    /// The To: menu, the orchestrator first, as on the page; only the sessions for a Mac that cannot take the orchestrator.
    public static func choices(_ dump: API.BrainDump, sessions: [String]) -> [DumpTarget] {
        (dump.send_to == nil ? [] : [.orchestrator]) + sessions.map { .session($0) }
    }

    /// The pinned session that left, when the send falls back to the orchestrator because of it: said under To:.
    public static func goneNote(_ dump: API.BrainDump, target: DumpTarget?) -> String? {
        guard target == .orchestrator, let name = dump.send_to?.gone else { return nil }
        return "\(name) \(gone)"
    }
}

/// Where a reviewed dump goes: Pointe's orchestrator voice (it answers or routes it), or one session, word for word.
public enum DumpTarget: Hashable, Sendable {
    case orchestrator
    case session(String)

    public var label: String {
        switch self {
        case .orchestrator: BrainDumpCopy.orchestrator
        case .session(let name): name
        }
    }
}

extension API.Status {
    public var dumping: Bool { brain_dump?.isDumping == true }
}
