import Foundation

/// Which coding agent runs a session. The vendors' own logos are not used (docs/design/brand-v6.md): the mark is a
/// neutral letter tile with the agent's name as its label. The table is assets/theme.json's.
public enum Harness {
    public static let marks: [String: (name: String, glyph: String)] = [
        "claude-code": (name: "Claude", glyph: "C"),
        "codex": (name: "Codex", glyph: "X"),
        "opencode": (name: "OpenCode", glyph: "O"),
        "pi": (name: "Pi", glyph: "P"),
    ]

    public static func mark(_ harness: String?) -> (name: String, glyph: String) {
        let id = harness.flatMap { $0.isEmpty ? nil : $0 } ?? "claude-code"
        return marks[id] ?? (name: id, glyph: String(id.prefix(1)).uppercased())
    }
}

/// The owner-voice lock's levels (docs/features/voice-lock.md), in rising order.
public enum VoiceLockLevel: String, CaseIterable, Identifiable, Sendable {
    case off, approvals, commands, everything
    public var id: String { rawValue }

    public var label: String {
        switch self {
        case .off: "Off"
        case .approvals: "Approvals"
        case .commands: "Commands"
        case .everything: "Everything"
        }
    }

    public var help: String {
        switch self {
        case .off: "Any voice works, as before."
        case .approvals: "A spoken yes counts only in your voice. A no counts from anyone."
        case .commands: "Only your voice reaches Pointe. Other voices are listed as ignored, with their words."
        case .everything: "Only your voice reaches Pointe. Other voices are dropped unseen."
        }
    }

    public var rank: Int { Self.allCases.firstIndex(of: self) ?? 0 }
    /// Lowering the lock (or turning it off) takes away a guard: the clients ask who is there first.
    public static func isLowering(from: VoiceLockLevel, to: VoiceLockLevel) -> Bool { to.rank < from.rank }
}
