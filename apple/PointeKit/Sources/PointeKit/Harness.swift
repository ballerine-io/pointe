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
