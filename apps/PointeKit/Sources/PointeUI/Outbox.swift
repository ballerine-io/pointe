import Foundation
import SwiftUI

/// The words a typed line shows on its way. The page's TYPED_COPY holds the same, but for Retry: the page puts a line it
/// could not send back in its box (tests/test_copy_parity.py).
enum TypedCopy {
    static let sending = "Sending…"
    static let sent = "Sent"
    static let notSent = "Not sent"
    static let retry = "Retry"
    static let noAnswer = "The Mac did not answer."
}

/// Typed lines on their way to the Mac. A line shows the moment Send is tapped, marked Sending; it is Sent once the Mac
/// took it, and leaves here when the Mac's own conversation shows it. A line the Mac did not answer is sent again with
/// the same id, so the Mac takes it once however many times it arrives (/voice/say's client_id); one it refused, or
/// never answered, stays with Retry. Nothing here waits on the network: the field clears at once.
struct Outbox: Equatable {
    enum State: Equatable {
        case sending
        case sent(turn: Int?)
        case failed(String)
    }

    struct Line: Identifiable, Equatable {
        let id: String
        let text: String
        var state: State
        /// The Mac's conversation did not show it yet when this many statuses had arrived (a sent line in a meeting,
        /// which adds no turn, leaves after the next one).
        var seen = 0
    }

    private(set) var lines: [Line] = []

    @discardableResult
    mutating func add(_ text: String, id: String = UUID().uuidString) -> Line {
        let line = Line(id: id, text: text, state: .sending)
        lines.append(line)
        return line
    }

    func line(_ id: String) -> Line? { lines.first { $0.id == id } }

    mutating func sending(_ id: String) { update(id) { $0.state = .sending } }
    mutating func sent(_ id: String, turn: Int?) { update(id) { $0.state = .sent(turn: turn); $0.seen = 0 } }
    mutating func failed(_ id: String, why: String) { update(id) { $0.state = .failed(why) } }

    /// A new status from the Mac: a sent line its conversation shows is drawn from there now.
    mutating func settle(_ talk: [API.Turn]) {
        let shown = Set(talk.map(\.id))
        lines = lines.compactMap { line in
            guard case .sent(let turn) = line.state else { return line }
            if let turn, shown.contains(turn) { return nil }
            var l = line
            l.seen += 1
            return turn == nil && l.seen > 1 ? nil : l
        }
    }

    private mutating func update(_ id: String, _ change: (inout Line) -> Void) {
        guard let i = lines.firstIndex(where: { $0.id == id }) else { return }
        change(&lines[i])
    }

    /// The waits between sends of a line the Mac did not answer: a weak link drops a request now and then.
    static let resendWaits: [TimeInterval] = [0.5, 1, 2, 4]
}

/// A typed line not in the Mac's conversation yet: your bubble, with where it stands under it.
struct OutgoingBubble: View {
    let line: Outbox.Line
    let retry: () -> Void

    var body: some View {
        VStack(alignment: .trailing, spacing: 4) {
            Bubble(turn: API.Turn(id: -1, who: "user", text: line.text, understood: nil, typed: nil, corrected: nil), polish: false)
                .opacity(line.state == .sending ? 0.75 : 1)
            HStack(spacing: 6) {
                switch line.state {
                case .sending:
                    Label(TypedCopy.sending, systemImage: "clock")
                case .sent:
                    Label(TypedCopy.sent, systemImage: "checkmark")
                case .failed(let why):
                    Label(TypedCopy.notSent, systemImage: "exclamationmark.circle").foregroundStyle(Brand.accent)
                        .help(why)
                    Button(TypedCopy.retry, action: retry)
                        .font(.brand(.caption2, .semibold)).tint(Brand.accent)
                        .accessibilityIdentifier("typedRetry")
                }
            }
            .labelStyle(.titleAndIcon)
            .font(.brand(.caption2))
            .foregroundStyle(Brand.muted)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("typedState")
        }
        .frame(maxWidth: .infinity, alignment: .trailing)
        .padding(.bottom, 14)
    }
}
