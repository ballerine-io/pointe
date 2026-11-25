import Foundation

/// Which coding agent runs a session. The vendors' own logos are not used (docs/design/brand-v6.md): the mark is the
/// agent's name, in plain text. The table is assets/theme.json's.
public enum Harness {
    public static let names: [String: String] = [
        "claude-code": "Claude",
        "codex": "Codex",
        "opencode": "OpenCode",
        "pi": "Pi",
    ]

    /// The agent's name as shown; an agent this build does not know is shown by its own id.
    public static func name(_ harness: String?) -> String {
        let id = harness.flatMap { $0.isEmpty ? nil : $0 } ?? "claude-code"
        return names[id] ?? id
    }
}
