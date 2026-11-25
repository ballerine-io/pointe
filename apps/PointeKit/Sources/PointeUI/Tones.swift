import SwiftUI

/// One sound per session (docs/features/session-tones.md): an optional short tone before a background session's
/// report, the same one for a session every time. The Mac makes the sound (pointe/tones.py); here is the setting, off
/// unless turned on, and the tone's name beside the session's agent, so the sound has something to see.
extension API {
    struct SessionTone: Decodable, Equatable {
        let index: Int
        let name: String
    }
}

/// The page's words (ui_tones.html) and tones.COPY, word for word (tests/test_tones.py).
enum TonesCopy {
    static let setting = "Session tones"
    static let hint = "A short tone before a background session's report, the same one for that session every time, so you know who is reporting before the first word."
    static func row(_ name: String) -> String { "tone: \(name)" }

    /// What a session's row says of its tone: nil until it has one. The Mac sends it only while the setting is on.
    static func label(_ session: API.Session) -> String? { session.tone.map { row($0.name) } }
}
