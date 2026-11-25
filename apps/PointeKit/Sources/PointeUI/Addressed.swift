import SwiftUI

/// Addressed speech (docs/features/addressed-speech.md): the microphone setting between Always on and push to talk,
/// "Only when I say Pointe". The Mac hears everything and acts only on a spoken turn that says Pointe's name or a
/// session's; the rule is the Mac's (pointe/addressed.py). Here: the setting's words, the switch's third choice, and the
/// state line, which says how to talk where it said "Listening".
extension API {
    struct Addressed: Decodable, Equatable {
        let on: Bool
        var open: Bool? = nil     // the name was just said alone: the next words need none
        var dropped: Int? = nil   // side talk dropped since Pointe started: a count, never the words
    }
}

/// The page's words (ui_addressed.html) and addressed.COPY, word for word (tests/test_addressed.py).
enum AddressedCopy {
    static let mode = "addressed"
    static let setting = "Only when I say Pointe"
    static let short = "Say “Pointe”"
    static let hint = "Pointe hears everything and acts only on words that start with its name, or a session's: “Pointe, what's billing doing”, “billing, run the tests”. Anything else is dropped, and its words are not kept."
    static let idle = "Say “Pointe” to talk"
    static let open = "Listening"

    /// The state line while nothing else holds: nil unless the mode is on.
    static func line(_ status: API.Status?) -> String? {
        guard let addressed = status?.addressed, addressed.on else { return nil }
        return addressed.open == true ? open : idle
    }
}
