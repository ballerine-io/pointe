import SwiftUI

/// Mute (docs/features/mute.md): one toggle beside the call's status line. Muted, Pointe never speaks: every line arrives
/// as text, and the line says "Writing…" where it would say "Speaking…". Each device keeps its own choice: it adds
/// `reading=1` to the call's address, and keeps what the Mac says when the choice changed by voice
/// ({"type": "reading", "on": …} on the call). The wire keeps the name it had as reading mode. Approvals are unchanged: a
/// tap, or a spoken yes after the read-out.
extension API {
    struct ReadingStatus: Decodable, Equatable {
        let on: Bool
        var held: String? = nil        // "drive": drive mode holds it, and Pointe talks until drive mode ends
        var read_through: Int? = nil   // what an app from before the mute button marked read; nothing shows it now
        var writing: Bool? = nil       // a line was just shown instead of spoken; nil from a Mac before the mute button
    }

    struct ReadingReply: Decodable {
        let reading: ReadingStatus?
        let applied: Bool?             // false with no call up: nothing changed on the Mac, this device keeps the choice
    }
}

/// The page's words (ui_mute.html), word for word.
enum MuteCopy {
    static let speaking = "Speaking…"
    static let writing = "Writing…"
    static let mute = "Mute Pointe"
    static let unmute = "Unmute Pointe"
    static let held = "Drive mode holds mute: Pointe talks while you drive."
    static let failed = "Mute did not change: the voice is not reachable."
}

/// This device's choice, and what the screen shows from it.
enum MuteChoice {
    static let key = "reading"  // reading mode's key: a device that chose it stays muted

    static func stored(_ defaults: UserDefaults = .standard) -> Bool { defaults.bool(forKey: key) }
    static func store(_ on: Bool, _ defaults: UserDefaults = .standard) { defaults.set(on, forKey: key) }

    /// A call is up (on this device or another): the call's state; none: this device's own choice.
    static func on(status: API.Status?, stored: Bool) -> Bool {
        if let status, status.connected, let reading = status.reading { return reading.on }
        return stored
    }

    /// On, and not held by drive mode: nothing is spoken.
    static func inEffect(status: API.Status?, stored: Bool) -> Bool {
        on(status: status, stored: stored) && status?.reading?.held == nil
    }

    /// Muted, and the Mac just showed a line it would have spoken: the status line says "Writing…".
    static func writing(status: API.Status?, stored: Bool) -> Bool {
        status?.connected == true && inEffect(status: status, stored: stored) && status?.reading?.writing == true
    }

    /// The call's address with the choice on it (`?reading=1`), so the greeting is already text.
    static func callURL(_ url: URL, on: Bool) -> URL {
        guard on, var parts = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return url }
        parts.queryItems = (parts.queryItems ?? []) + [URLQueryItem(name: "reading", value: "1")]
        return parts.url ?? url
    }

    /// The Mac's {"type": "reading", "on": true|false}: the choice to keep; nil for any other message.
    static func message(_ message: [String: Any]) -> Bool? {
        guard message["type"] as? String == "reading" else { return nil }
        return message["on"] as? Bool
    }
}

/// Beside the status line: a speaker with a slash. A tap mutes Pointe, and unmutes it when it is filled.
struct MuteButton: View {
    let on: Bool
    var held = false  // drive mode holds it: Pointe talks, and the button says why
    let toggle: () -> Void

    static func label(on: Bool) -> String { on ? MuteCopy.unmute : MuteCopy.mute }
    static func symbol(on: Bool) -> String { on ? "speaker.slash.fill" : "speaker.slash" }
    static func hint(on: Bool, held: Bool) -> String? { on && held ? MuteCopy.held : nil }

    var body: some View {
        Button(action: toggle) {
            Image(systemName: Self.symbol(on: on))
                .font(.brand(.subheadline, .medium))
                .foregroundStyle(on ? Brand.accent : Brand.text)
                .frame(width: 32, height: 32)
                .background(Brand.raised, in: Circle())
                .overlay(Circle().stroke(on ? Brand.orange : Brand.line, lineWidth: on ? 2 : 1))
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .help(Self.hint(on: on, held: held) ?? Self.label(on: on))
        .accessibilityLabel(Self.label(on: on))
        .accessibilityHint(Self.hint(on: on, held: held) ?? "")
        .accessibilityAddTraits(on ? .isSelected : [])
        .accessibilityIdentifier("muteButton")
    }
}
