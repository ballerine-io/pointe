import SwiftUI

/// Skip (docs/features/skip.md): one button beside the call's status line, after the mute button, shown only while
/// Pointe speaks. A tap skips the line being said and Pointe goes on to the next one that waits; the line's words stay
/// in the conversation. The Mac app also has a key for it that works from any app (Settings, "Skip shortcut").
/// The words are the page's (ui_skip.html), word for word.
enum SkipCopy {
    static let skip = "Skip this message"
    static let failed = "Skip did not reach the voice."
}

enum SkipRule {
    /// While Pointe's voice is heard. Muted, nothing is said, so there is nothing to skip.
    static func shows(speaking: Bool, muted: Bool) -> Bool { speaking && !muted }
}

/// Beside the status line, after the mute button: play-to-the-end. A tap skips what Pointe is saying.
struct SkipButton: View {
    let skip: () -> Void

    static let symbol = "forward.end"

    var body: some View {
        Button(action: skip) {
            Image(systemName: Self.symbol)
                .font(.brand(.subheadline, .medium))
                .foregroundStyle(Brand.text)
                .frame(width: 32, height: 32)
                .background(Brand.raised, in: Circle())
                .overlay(Circle().stroke(Brand.line, lineWidth: 1))
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .help(SkipCopy.skip)
        .accessibilityLabel(SkipCopy.skip)
        .accessibilityIdentifier("skipButton")
    }
}
