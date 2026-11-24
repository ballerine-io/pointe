import SwiftUI

/// Reading mode (docs/features/reading-mode.md): Pointe never speaks; every line arrives as text, unread until you tap it,
/// talk or type. Each device keeps its own choice: it adds `reading=1` to the call's address, and keeps what the Mac says
/// when the choice changed by voice ({"type": "reading", "on": …} on the call). Approvals are unchanged: a tap, or a
/// spoken yes after the read-out.
extension API {
    struct ReadingStatus: Decodable, Equatable {
        let on: Bool
        var held: String? = nil        // "drive": drive mode holds it, and Pointe talks until drive mode ends
        var read_through: Int? = nil   // the newest of Pointe's lines read: talk ids up to it are read
    }

    struct ReadingReply: Decodable {
        let reading: ReadingStatus?
        let applied: Bool?             // false with no call up: nothing changed on the Mac, this device keeps the choice
    }

    /// Session mode: what the other sessions said meanwhile, held for the screens and never spoken (scope.py).
    struct HeldStatus: Decodable, Equatable {
        let count: Int
        let line: String?
        var approvals: Int? = nil
        var items: [HeldItem]? = nil
    }

    struct HeldItem: Decodable, Equatable, Hashable {
        let session: String?
        let kind: String?
        let line: String
        let at: Double?
    }
}

/// The page's words (ui_reading.html), word for word.
enum ReadingCopy {
    static let button = "Read"
    static let buttonOn = "Reading"
    static let title = "Reading mode: Pointe writes, you read."
    static let body = "Nothing is spoken. Talk or type as usual. A reply stays unread until you tap it, talk or type."
    static let back = "Talk again"
    static let unread = "Unread"
    static let read = "Read"
    static let markRead = "Mark all read"
    static let held = "Drive mode holds reading mode: Pointe talks while you drive."
    static let failed = "Reading mode did not change: the voice is not reachable."
}

/// The badge of held news, as the page words it: the Mac's own line, and "session · line" for each item.
enum HeldCopy {
    static let tell = "Tell me"

    static func badge(_ held: API.HeldStatus?) -> String? {
        guard let held, held.count > 0 else { return nil }
        return held.line?.isEmpty == false ? held.line : "\(held.count) updates from other sessions"
    }

    static func item(_ item: API.HeldItem) -> String {
        guard let session = item.session, !session.isEmpty else { return item.line }
        return "\(session) · \(item.line)"
    }
}

/// This device's choice, and what the screen shows from it.
enum ReadingChoice {
    static let key = "reading"

    static func stored(_ defaults: UserDefaults = .standard) -> Bool { defaults.bool(forKey: key) }
    static func store(_ on: Bool, _ defaults: UserDefaults = .standard) { defaults.set(on, forKey: key) }

    /// A call is up (on this device or another): the call's state; none: this device's own choice.
    static func on(status: API.Status?, stored: Bool) -> Bool {
        if let status, status.connected, let reading = status.reading { return reading.on }
        return stored
    }

    /// On, and not held by drive mode: the replies carry Unread and Read.
    static func inEffect(status: API.Status?, stored: Bool) -> Bool {
        on(status: status, stored: stored) && status?.reading?.held == nil
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

/// Above the controls while reading mode is on, like the whisper card.
struct ReadingCard: View {
    let held: Bool
    let back: () -> Void
    let markRead: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(ReadingCopy.title, systemImage: "text.bubble").font(.brand(.subheadline, .semibold))
            Text(held ? ReadingCopy.held : ReadingCopy.body)
                .font(.brand(.footnote)).foregroundStyle(Brand.muted).fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 8) {
                Button(ReadingCopy.markRead, action: markRead).buttonStyle(.brandQuiet).accessibilityIdentifier("readingMarkRead")
                Button(ReadingCopy.back, action: back).buttonStyle(.brandQuiet).accessibilityIdentifier("readingOff")
            }
            .font(.brand(.subheadline))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Brand.raised, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.orangeLine))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("readingCard")
    }
}

/// Under one of Pointe's lines in reading mode: Unread (accent) until read, then Read (muted).
struct ReadMark: View {
    let unread: Bool

    var body: some View {
        Label(unread ? ReadingCopy.unread : ReadingCopy.read, systemImage: unread ? "circle.fill" : "checkmark")
            .labelStyle(.titleAndIcon)
            .font(.brand(.caption2, unread ? .semibold : .regular))
            .foregroundStyle(unread ? Brand.accent : Brand.muted)
            .accessibilityIdentifier(unread ? "readingUnread" : "readingRead")
    }
}

/// Session mode: a quiet chip with the count of what the other sessions said. A tap shows the lines, and Tell me has
/// Pointe say them (as "anything from the others?" does). Nothing here is spoken by itself.
struct HeldBadge: View {
    let held: API.HeldStatus
    let tell: () -> Void
    @State private var open: Bool

    init(held: API.HeldStatus, open: Bool = false, tell: @escaping () -> Void) {
        self.held = held
        self.tell = tell
        _open = State(initialValue: open)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button { withAnimation(.snappy) { open.toggle() } } label: {
                HStack(spacing: 6) {
                    Image(systemName: "tray.full")
                    Text(HeldCopy.badge(held) ?? "")
                    Image(systemName: open ? "chevron.down" : "chevron.right").font(.brand(.caption2))
                }
                .font(.brand(.footnote, .medium)).foregroundStyle(Brand.muted)
                .padding(.horizontal, 12).padding(.vertical, 6)
                .background(Brand.raised, in: Capsule())
                .overlay(Capsule().stroke(Brand.line))
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("heldBadge")
            if open {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array((held.items ?? []).enumerated()), id: \.offset) { _, item in
                        Text(HeldCopy.item(item)).font(.brand(.footnote)).fixedSize(horizontal: false, vertical: true)
                    }
                    Button(HeldCopy.tell, action: tell).buttonStyle(.brandQuiet).font(.brand(.subheadline))
                        .accessibilityIdentifier("heldTell")
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Brand.card, in: RoundedRectangle(cornerRadius: 16))
                .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.line))
                .transition(.opacity)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
