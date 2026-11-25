import SwiftUI

/// The approvals record (docs/features/approvals-record.md): every answer to a permission request that went through
/// Pointe, newest first, read by the Mac from its own journal (`GET /voice/approvals`). When, by voice or by a tap, the
/// exact request, and the voice lock's score of a spoken answer. Read only: nothing here answers anything.
extension API {
    struct Approval: Decodable, Equatable, Identifiable {
        let at: String              // the Mac's clock: "2026-11-20 09:14:02.121"
        let session: String
        var machine: String? = nil
        let request_id: String
        let decision: String        // "allow" or "deny"
        let by: String              // "voice", "tap", "notification", "other"
        let request: String         // the tool, then its input, as the card showed it
        var cut: Bool? = nil
        var lock: String? = nil     // the voice lock's level when it was answered
        var score: Double? = nil    // a spoken answer's score; nil: a tap, or a voice the lock did not score

        var id: String { "\(at) \(session) \(request_id)" }
    }

    struct ApprovalsPage: Decodable, Equatable {
        let approvals: [Approval]
    }
}

/// The page's words (ui_approvals.html) and approvals.COPY, word for word (tests/test_approvals.py).
enum ApprovalsCopy {
    static let title = "Approvals record"
    static let lede = "Every answer to a request that went through Pointe on this Mac, newest first. An answer given in a session's own terminal is not here."
    static let empty = "No request has been answered through Pointe yet."
    static let allow = "Approved"
    static let deny = "Denied"
    static let voice = "by voice"
    static let tap = "by a tap"
    static let notification = "from a notification"
    static let other = "by Pointe"
    static func score(_ lock: String, _ score: String) -> String { "Voice lock \(lock): score \(score)" }
    static func unscored(_ lock: String) -> String { "Voice lock \(lock): the voice was not scored" }
    static let lockOff = "Voice lock off: the voice was not checked"
    static let cut = "The request was longer than the record keeps: this is its start."
    static let failed = "The record did not load from the Mac."

    static func decision(_ a: API.Approval) -> String { a.decision == "allow" ? allow : deny }

    static func by(_ a: API.Approval) -> String {
        switch a.by {
        case "voice": voice
        case "tap": tap
        case "notification": notification
        default: other
        }
    }

    /// The voice lock's part of a line: only a spoken answer has one.
    static func lock(_ a: API.Approval) -> String? {
        guard a.by == "voice" else { return nil }
        let level = a.lock ?? "off"
        if level == "off" { return lockOff }
        guard let score = a.score else { return unscored(level) }
        return Self.score(level, String(format: "%.2f", score))
    }

    /// "Approved by voice", "Denied by a tap": the head of a row, and with the rest what VoiceOver reads.
    static func head(_ a: API.Approval) -> String { "\(decision(a)) \(by(a))" }

    /// "20 Nov, 09:14": the Mac's own clock, as it wrote it.
    static func when(_ at: String) -> String {
        let parts = at.split(separator: " ")
        guard parts.count == 2, parts[0].count == 10, parts[1].count >= 5 else { return at }
        let day = parts[0].split(separator: "-")
        let months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        guard day.count == 3, let month = Int(day[1]), (1...12).contains(month), let d = Int(day[2]) else { return at }
        return "\(d) \(months[month - 1]), \(parts[1].prefix(5))"
    }

    static func spoken(_ a: API.Approval) -> String {
        [head(a), a.machine.map { "\(a.session) on \($0)" } ?? a.session, when(a.at), a.request, lock(a)].compactMap { $0 }.joined(separator: ", ")
    }
}

struct ApprovalsSheet: View {
    let load: () async -> [API.Approval]?
    @Environment(\.dismiss) private var dismiss
    @State private var rows: [API.Approval]?
    @State private var failed = false

    var body: some View {
        NavigationStack {
            BrandForm {
                Section {
                    if failed {
                        Text(ApprovalsCopy.failed).font(.brand(.footnote)).foregroundStyle(Brand.accent).accessibilityIdentifier("approvalsFailed")
                    } else if let rows, rows.isEmpty {
                        Text(ApprovalsCopy.empty).foregroundStyle(Brand.muted).accessibilityIdentifier("approvalsEmpty")
                    } else if let rows {
                        ForEach(rows) { row($0) }
                    } else {
                        ProgressView().frame(maxWidth: .infinity)
                    }
                } header: {
                    Text(ApprovalsCopy.lede).textCase(nil).brandFootnote()
                }
            }
            .sheetTitle(ApprovalsCopy.title)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .accessibilityIdentifier("approvalsSheet")
        }
        .task {
            if let loaded = await load() { rows = loaded } else { failed = true }
        }
    }

    private func row(_ a: API.Approval) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Image(systemName: a.decision == "allow" ? "checkmark.circle.fill" : "xmark.circle.fill")
                    .foregroundStyle(a.decision == "allow" ? Brand.success : Brand.dangerText)
                Text(ApprovalsCopy.head(a)).font(.brand(.subheadline, .semibold))
                Spacer(minLength: 8)
                Text(ApprovalsCopy.when(a.at)).font(.brand(.caption)).foregroundStyle(Brand.muted)
            }
            Text(a.machine.map { "\(a.session) · \($0)" } ?? a.session).font(.brand(.caption)).foregroundStyle(Brand.muted)
            Text(a.request).font(.system(.footnote, design: .monospaced)).foregroundStyle(Brand.text)
                .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                .padding(8).background(Brand.raised2, in: RoundedRectangle(cornerRadius: 8))  // on a Brand.cell row: raised is the cell's own colour in dark
            if a.cut == true { Text(ApprovalsCopy.cut).font(.brand(.caption)).foregroundStyle(Brand.muted) }
            if let lock = ApprovalsCopy.lock(a) { Text(lock).font(.brand(.caption)).foregroundStyle(Brand.muted) }
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(ApprovalsCopy.spoken(a))
        .accessibilityIdentifier("approval.\(a.request_id)")
    }
}
