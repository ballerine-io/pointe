import SwiftUI

extension API {
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
