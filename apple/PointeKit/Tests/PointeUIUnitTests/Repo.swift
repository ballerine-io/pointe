import Foundation

/// The repository these tests are in: some of them hold the app's words to the page's (ui.html), and one reads a
/// source file. Tests/PointeUIUnitTests is five folders below the root.
enum Repo {
    static let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()

    static func text(_ path: String) throws -> String {
        try String(contentsOf: root.appendingPathComponent(path), encoding: .utf8)
    }

    /// A source file of the shared module.
    static func source(_ name: String) throws -> String { try text("apple/PointeKit/Sources/PointeUI/\(name)") }
}
