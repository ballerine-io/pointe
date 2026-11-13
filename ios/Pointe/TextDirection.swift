import SwiftUI

/// Which way a message reads: from its first strong letter, as the page's dir="auto", never from the phone's language.
/// Hebrew, Arabic, Persian and Urdu read from the right, so their full stop sits at the left end; a sentence that starts
/// in Hebrew stays right to left with English words inside it. Digits and punctuation do not decide.
enum TextDirection {
    static func of(_ text: String) -> LayoutDirection {
        for scalar in text.unicodeScalars {
            if scalar.value == 0x200F || scalar.value == 0x061C { return .rightToLeft }  // RLM, ALM: strong marks
            if scalar.value == 0x200E { return .leftToRight }                            // LRM
            guard scalar.properties.isAlphabetic else { continue }
            return rightToLeftScript(scalar.value) ? .rightToLeft : .leftToRight
        }
        return .leftToRight
    }

    /// A message inside a sentence of ours ("Wants to say: …"): isolated, so it keeps its own direction (U+2068 first
    /// strong isolate is this same rule) instead of taking the sentence's, which put a Hebrew full stop at its start.
    static func isolated(_ text: String) -> String { "\u{2068}\(text)\u{2069}" }

    /// Hebrew to NKo and the Arabic extensions, the Hebrew and Arabic presentation forms, and the right-to-left planes.
    private static func rightToLeftScript(_ v: UInt32) -> Bool {
        (0x0590...0x08FF).contains(v) || (0xFB1D...0xFDFF).contains(v) || (0xFE70...0xFEFF).contains(v)
            || (0x10800...0x10FFF).contains(v) || (0x1E800...0x1EFFF).contains(v)
    }
}

extension View {
    /// Lays the text out in its own direction: the base direction of the line, and `leading` is its reading start.
    @ViewBuilder
    func readingDirection(of text: String) -> some View {
        if TextDirection.of(text) == .rightToLeft {
            multilineTextAlignment(.leading).environment(\.layoutDirection, .rightToLeft)
        } else {
            environment(\.layoutDirection, .leftToRight)
        }
    }
}
