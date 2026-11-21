import SwiftUI

// Conflict alarm (docs/features/conflict-alarm.md): two sessions that disagree about the same work.
// The card shows both claims. Ask puts one side's question to the Mac as the user's own typed words, so the voice sends
// it through the usual checks and it can never approve anything; Dismiss quiets that pair for the call. Nothing here
// sends by itself.

extension API {
    struct Conflict: Decodable, Equatable, Identifiable {
        let id: String
        let a: String
        let b: String
        let agent_a: String?
        let agent_b: String?
        let claim_a: String
        let claim_b: String
        let at_a: Double?
        let at_b: Double?
        let why: String?
        let severity: String?        // high, normal
        let branches: Branches?      // only when the two are on different branches
        var asked: [String]?         // "a", "b": the sides already asked

        func name(_ side: String) -> String { side == "a" ? a : b }
        func wasAsked(_ side: String) -> Bool { asked?.contains(side) == true }
    }

    struct Branches: Decodable, Equatable {
        let a: String
        let b: String
    }

    /// action "ask" (with side "a" or "b") or "dismiss". 409 while no call is up or a meeting is on.
    func conflict(_ id: String, action: String, side: String? = nil) async throws {
        var body: [String: Any] = ["action": action, "id": id]
        if let side { body["side"] = side }
        let (data, response) = try await send(request("voice/conflicts", method: "POST", body: body))
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw Failure.status(code, detail ?? "HTTP \(code)")
        }
    }
}

/// Word for word the page's copy (ui.html): the two must not drift.
enum ConflictCopy {
    static let title = "Two sessions disagree"
    static let dismiss = "Dismiss"
    static let inMeeting = "In a meeting, nothing goes to a session: ask after it ends."
    static let connect = "Connect to ask."
    static let settingsTitle = "Conflict alarm"
    static let check = "Check sessions against each other"
    static let alarm = "Alarm"
    static let spoken = "Spoken"
    static let cardOnly = "Card only"
    static let footer = "When two sessions disagree about the same work, Pointe shows both claims and asks whether to put the question to one of them. It never asks a session on its own. In a meeting it is a card only."

    static func ask(_ name: String) -> String { "Ask \(name)" }
    static func more(_ n: Int) -> String { "\(n) more disagreement\(n == 1 ? "" : "s")" }
    static func asked(_ name: String) -> String { "Asked \(name)" }
    static func branches(_ b: API.Branches) -> String { "On different branches: \(b.a) and \(b.b)" }

    /// The Mac's refusals, as the page shows them.
    static func refusal(_ detail: String) -> String {
        switch detail {
        case "no call is up": connect
        case "no such conflict": "That conflict is gone."
        case "nothing goes to a session during a meeting": inMeeting
        default: detail.isEmpty ? "Not done." : detail
        }
    }

    static func time(_ at: Double?) -> String {
        guard let at else { return "" }
        return Date(timeIntervalSince1970: at).formatted(date: .omitted, time: .shortened)
    }
}

struct ConflictCard: View {
    let conflict: API.Conflict
    var showAgents = false
    let inMeeting: Bool
    let live: Bool
    /// Nil when the Mac took it; otherwise its reason.
    let act: (String, String?) async -> String?
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label { Text(ConflictCopy.title) } icon: {
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(Brand.accent)
            }
            .font(.brand(.headline))
            if let branches = conflict.branches {
                Text(ConflictCopy.branches(branches)).font(.brand(.caption)).foregroundStyle(Brand.muted)
            }
            claim(conflict.a, conflict.agent_a, conflict.claim_a, conflict.at_a, id: "conflictClaimA")
            claim(conflict.b, conflict.agent_b, conflict.claim_b, conflict.at_b, id: "conflictClaimB")
            if let why = conflict.why, !why.isEmpty {
                Text(why).font(.brand(.caption)).foregroundStyle(Brand.muted)
            }
            if inMeeting {
                Text(ConflictCopy.inMeeting).font(.brand(.caption)).foregroundStyle(Brand.muted).accessibilityIdentifier("conflictMeetingNote")
            } else if !live {
                Text(ConflictCopy.connect).font(.brand(.caption)).foregroundStyle(Brand.muted)
            }
            // A session's name is never cut: one row when all three fit, else the two questions over Dismiss, else a column.
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 8) { ask("a"); ask("b"); dismissButton }
                VStack(spacing: 8) { HStack(spacing: 8) { ask("a"); ask("b") }; dismissButton }
                VStack(spacing: 8) { ask("a", wraps: true); ask("b", wraps: true); dismissButton }
            }
            .controlSize(.regular)
            if let error {
                Text(error).font(.brand(.caption)).foregroundStyle(Brand.accent).accessibilityIdentifier("conflictError")
            }
        }
        .padding(16)
        .background(Brand.card, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.orangeLine))
        .sensoryFeedback(.warning, trigger: conflict.id)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("conflictCard")
    }

    private func ask(_ side: String, wraps: Bool = false) -> some View {
        let name = conflict.name(side)
        return Button { run("ask", side) } label: {
            Text(conflict.wasAsked(side) ? ConflictCopy.asked(name) : ConflictCopy.ask(name))
                .lineLimit(wraps ? 3 : 1).multilineTextAlignment(.center).padding(.vertical, wraps ? 6 : 0).frame(maxWidth: .infinity)
        }
        .buttonStyle(.brandQuiet)
        .disabled(busy || conflict.wasAsked(side) || inMeeting || !live)
        .accessibilityIdentifier("conflictAsk-\(side)")
    }

    private var dismissButton: some View {
        Button { run("dismiss", nil) } label: { Text(ConflictCopy.dismiss).frame(maxWidth: .infinity) }
            .buttonStyle(.brandQuiet)
            .disabled(busy)
            .accessibilityIdentifier("conflictDismiss")
    }

    private func claim(_ name: String, _ agent: String?, _ text: String, _ at: Double?, id: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 6) {
                Text(name).font(.brand(.subheadline, .semibold)).foregroundStyle(Brand.accent)
                if showAgents, let agent { Text(agent).font(.brand(.caption2)).foregroundStyle(Brand.muted) }
                Text(ConflictCopy.time(at)).font(.brand(.caption)).foregroundStyle(Brand.muted)
            }
            Text(text).readingDirection(of: text).font(.brand(.subheadline))
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier(id)
    }

    private func run(_ action: String, _ side: String?) {
        busy = true
        Task {
            error = await act(action, side)
            busy = false
        }
    }
}

/// Settings → Conflict alarm: the same two controls as the page's Settings.
struct ConflictSettingsSheet: View {
    let load: () async -> API.Prefs?
    let save: ([String: any Sendable]) async -> Bool
    @Environment(\.dismiss) private var dismiss
    @State private var prefs: API.Prefs?
    @State private var loaded = false
    @State private var failed = false

    var body: some View {
        NavigationStack {
            BrandForm {
                if var p = prefs {
                    Section {
                        Toggle(ConflictCopy.check, isOn: Binding(get: { p.conflictsOn }, set: { p.conflictsOn = $0; update(p, ["conflicts.on": $0]) }))
                            .tint(Brand.orange)
                            .accessibilityIdentifier("conflictsOn")
                        Picker(ConflictCopy.alarm, selection: Binding(get: { p.conflictsSpoken }, set: { p.conflictsSpoken = $0; update(p, ["conflicts.spoken": $0]) })) {
                            Text(ConflictCopy.spoken).tag(true)
                            Text(ConflictCopy.cardOnly).tag(false)
                        }
                        .disabled(!p.conflictsOn)
                        .accessibilityIdentifier("conflictsSpoken")
                    } footer: { Group { Text(ConflictCopy.footer) }.brandFootnote() }
                    if failed {
                        Label("The Mac did not take that setting. Is Pointe on the Mac up to date?", systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(Brand.accent)
                    }
                } else if loaded {
                    Label("The Mac did not send its settings. Is Pointe on the Mac up to date and reachable?",
                          systemImage: "exclamationmark.triangle.fill").foregroundStyle(Brand.accent)
                } else {
                    ProgressView()
                }
            }
            .scrollContentBackground(.hidden)
            .sheetTitle(ConflictCopy.settingsTitle)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .task { prefs = await load(); loaded = true }
    }

    private func update(_ p: API.Prefs, _ change: [String: any Sendable]) {
        let before = prefs
        prefs = p
        Task {
            if !(await save(change)) { prefs = before; failed = true } else { failed = false }
        }
    }
}
