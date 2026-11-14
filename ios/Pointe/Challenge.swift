import SwiftUI

// Challenge me: the voice plays devil's advocate against your plan. The Mac runs it and enforces its rules (nothing
// is sent while it is on, it never approves anything (a spoken "stop" also denies a pending request, as any "no" does), never during a meeting); the phone starts it, shows the
// exchange and ends it.

extension API {
    struct ChallengeItem: Decodable, Equatable, Hashable {
        let kind: String            // objection, rebuttal, verdict
        let text: String
        let at: Double?
    }

    /// On now, or the last one after it ended (`on` false) until a new one starts.
    struct ChallengeStatus: Decodable, Equatable {
        var id: String
        var on: Bool
        let since: Double?
        var ended_at: Double?
        var plan: String?
        let sessions: [String]?
        let objections: Int?
        let verdict: String?
        let evidence: Int?
        var items: [ChallengeItem]?
    }
}

/// Word for word the page's copy (ui.html): the two must not drift.
enum ChallengeCopy {
    static let menuItem = "Challenge"
    static let fromDump = "Challenge it"
    static let state = "Challenging"
    static let lede = "I argue against your plan, one objection at a time. Nothing is sent while it's on."
    static let planHeading = "The plan"
    static let noPlan = "No plan yet: say it in a sentence or two."
    static let end = "End challenge"
    static let hint = "Or say “you've made your point”, “verdict” or “back to normal”."
    static let close = "Close"

    static func title(on: Bool) -> String { on ? "Challenge" : "Challenge ended" }

    static func label(_ kind: String) -> String {
        switch kind {
        case "rebuttal": "You"
        case "verdict": "Verdict"
        default: "Objection"
        }
    }

    static func plan(_ text: String?) -> String {
        let t = (text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty ? noPlan : t
    }

    /// While on it always shows; once ended, until closed on this phone. A new challenge has a new id and shows again.
    static func shown(_ c: API.ChallengeStatus?, dismissed: String?) -> Bool {
        guard let c else { return false }
        return c.on || c.id != dismissed
    }

    static func rightToLeft(_ text: String) -> Bool { TextDirection.of(text) == .rightToLeft }
}

/// Text that sits on the side its own language reads from, whatever the phone's language.
private struct NaturalText: View {
    let text: String
    var body: some View {
        let rtl = ChallengeCopy.rightToLeft(text)
        Text(text)
            .readingDirection(of: text)
            .frame(maxWidth: .infinity, alignment: rtl ? .trailing : .leading)
    }
}

struct ChallengePanel: View {
    let challenge: API.ChallengeStatus
    let problem: String?
    let end: () async -> Void
    let close: () -> Void
    @State private var busy = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 10) {
                Image(systemName: "figure.fencing").font(.title2).foregroundStyle(Brand.orange)
                    .symbolEffect(.pulse, options: .repeating, isActive: challenge.on)
                VStack(alignment: .leading, spacing: 2) {
                    Text(ChallengeCopy.title(on: challenge.on)).font(.title2.bold())
                        .accessibilityIdentifier("challenge.title")
                    Text(ChallengeCopy.lede).font(.subheadline).foregroundStyle(.secondary)
                }
            }
            ScrollViewReader { scroller in
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(ChallengeCopy.planHeading).font(.caption.bold()).foregroundStyle(.secondary)
                            NaturalText(text: ChallengeCopy.plan(challenge.plan))
                                .font(.body)
                                .foregroundStyle((challenge.plan ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                                                 ? .secondary : .primary)
                        }
                        .accessibilityElement(children: .combine)
                        .accessibilityIdentifier("challenge.plan")
                        ForEach(Array((challenge.items ?? []).enumerated()), id: \.offset) { _, item in
                            row(item)
                        }
                        Color.clear.frame(height: 1).id("end")
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .defaultScrollAnchor(.bottom)
                .onChange(of: challenge.items?.count) { withAnimation(.smooth) { scroller.scrollTo("end", anchor: .bottom) } }
            }
            if let problem {
                Label(problem, systemImage: "exclamationmark.triangle.fill").font(.footnote).foregroundStyle(Brand.orange)
            }
            if challenge.on {
                Text(ChallengeCopy.hint).font(.footnote).foregroundStyle(.secondary)
                Button {
                    busy = true
                    Task { await end(); busy = false }
                } label: {
                    Text(ChallengeCopy.end).font(.headline).frame(maxWidth: .infinity).padding(.vertical, 6)
                }
                .buttonStyle(.borderedProminent).tint(Brand.orange).controlSize(.large)
                .disabled(busy)
                .accessibilityIdentifier("challenge.end")
            } else {
                Button(action: close) {
                    Text(ChallengeCopy.close).font(.headline).frame(maxWidth: .infinity).padding(.vertical, 6)
                }
                .buttonStyle(.bordered).tint(.gray).controlSize(.large)
                .accessibilityIdentifier("challenge.close")
            }
        }
        .padding(20)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Brand.orange.opacity(0.06), in: RoundedRectangle(cornerRadius: 24))
        .overlay(RoundedRectangle(cornerRadius: 24).stroke(Brand.orange.opacity(0.35)))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("challenge.panel")
    }

    private func row(_ item: API.ChallengeItem) -> some View {
        let mine = item.kind == "rebuttal"
        return VStack(alignment: .leading, spacing: 4) {
            Text(ChallengeCopy.label(item.kind)).font(.caption.bold())
                .foregroundStyle(item.kind == "verdict" ? Brand.orange : .secondary)
            NaturalText(text: item.text).font(.body)
        }
        .padding(.horizontal, 12).padding(.vertical, 9)
        .background(mine ? AnyShapeStyle(Brand.orange.opacity(0.18)) : AnyShapeStyle(Brand.card), in: RoundedRectangle(cornerRadius: 14))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(ChallengeCopy.label(item.kind)): \(item.text)")
        .accessibilityIdentifier("challenge.item.\(item.kind)")
    }
}
