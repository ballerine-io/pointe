import SwiftUI

/// What the New session sheet asks of the call: Face ID as for Approve, what the Mac offers, and the start itself.
struct NewSessionActions {
    let ownerCheck: (String) async -> Bool
    let options: () async throws -> NewSession.Options
    let start: (NewSession.Draft) async throws -> Void
}

/// Start a coding agent in a folder you already work in. Everything offered comes from the Mac; Start asks for Face ID,
/// as Approve does, and a refusal stays here in the Mac's words.
struct NewSessionSheet: View {
    static let faceIDReason = "Start a new session"

    let actions: NewSessionActions
    @Environment(\.dismiss) private var dismiss
    @State private var options: NewSession.Options?
    @State private var draft = NewSession.Draft()
    @State private var problem: String?
    @State private var busy = false

    var body: some View {
        NavigationStack {
            BrandForm {
                Section {} header: {  // a header keeps the form's text inset: a zero-inset row clipped the first letters
                    Text(NewSessionCopy.lede).brandFootnote().accessibilityIdentifier("newSessionLede")
                }
                if let options { fields(options) }
                if let problem {
                    Section { Text(problem).foregroundStyle(Brand.accent).accessibilityIdentifier("newSessionProblem") }
                }
            }
            .sheetTitle(NewSessionCopy.title)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(NewSessionCopy.cancel) { dismiss() }.accessibilityIdentifier("newSessionCancel")
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(NewSessionCopy.start) { Task { await start() } }
                        .disabled(busy || options.map(draft.canStart) != true)
                        .accessibilityIdentifier("newSessionStart")
                }
            }
            .task {
                do {
                    let fresh = try await actions.options()
                    options = fresh
                    draft = NewSession.Draft(fresh)
                } catch { problem = Self.refusal(error) }
            }
        }
    }

    @ViewBuilder
    private func fields(_ options: NewSession.Options) -> some View {
        KickerSection(NewSessionCopy.agent) {
            ForEach(options.harnesses) { agent in
                choice(agent.title, detail: agent.available ? nil : agent.why, on: draft.harness == agent.name, available: agent.available,
                       id: "newSessionAgent.\(agent.name)") { draft.harness = agent.name }
            }
            if draft.harness == "claude-code" {
                Text(NewSessionCopy.claudeNote).brandFootnote().accessibilityIdentifier("newSessionClaudeNote")
            }
        }
        if options.showsMachines {
            KickerSection(NewSessionCopy.machine) {
                ForEach(options.machines) { machine in
                    choice(machine.name, detail: machine.available ? nil : machine.why, on: draft.machine == machine.name, available: machine.available,
                           id: "newSessionMachine.\(machine.name)") { draft.machine = machine.name }
                }
            }
        }
        KickerSection(NewSessionCopy.folder) {
            if options.folders.isEmpty {
                Text(NewSessionCopy.noFolders).foregroundStyle(Brand.muted).accessibilityIdentifier("newSessionNoFolders")
            }
            ForEach(options.folders) { folder in
                choice(folder.name, detail: folder.path, on: draft.folder == folder.path, id: "newSessionFolder.\(folder.name)") { draft.folder = folder.path }
            }
        }
        KickerSection(NewSessionCopy.name) {
            TextField(NewSessionCopy.namePlaceholder, text: $draft.name)
                .plainEntry()
                .accessibilityIdentifier("newSessionName")
        }
        KickerSection(NewSessionCopy.prompt) {
            TextField(NewSessionCopy.promptPlaceholder, text: $draft.prompt, axis: .vertical).lineLimit(3...8)
                .accessibilityIdentifier("newSessionPrompt")
        }
    }

    /// One of a few: the name, under it the path or why it cannot be picked, and a check on the one picked.
    private func choice(_ title: String, detail: String?, on: Bool, available: Bool = true, id: String, pick: @escaping () -> Void) -> some View {
        Button(action: pick) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).foregroundStyle(.primary)
                    if let detail { Text(detail).font(.brand(.caption)).foregroundStyle(Brand.muted).lineLimit(3).truncationMode(.middle) }
                }
                Spacer()
                if on { Image(systemName: "checkmark").font(.brand(.body, .semibold)).foregroundStyle(Brand.accent) }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!available)
        .opacity(available ? 1 : 0.55)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(on ? .isSelected : [])
        .accessibilityIdentifier(id)
    }

    private func start() async {
        guard let options, draft.canStart(options) else { return }
        busy = true
        defer { busy = false }
        guard await actions.ownerCheck(Self.faceIDReason) else { return }
        do {
            try await actions.start(draft)
            dismiss()
        } catch { problem = Self.refusal(error) }
    }

    /// A refusal in the Mac's own words; a Mac that is away, or too old to start sessions, each get a line.
    static func refusal(_ error: Error) -> String {
        guard case API.Failure.status(let code, let detail) = error else { return "The Mac did not answer." }
        if detail.hasPrefix("HTTP ") { return code == 404 ? "Pointe on the Mac does not start sessions yet: update it." : "The Mac did not do it." }
        return detail
    }
}

/// A session Pointe is starting, or one that did not start, under the sessions: no actions, it becomes a session by itself.
struct StartingRow: View {
    let row: NewSession.Starting

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Circle().stroke(Brand.dim).frame(width: 9, height: 9)  // a ring: not a session yet
                Text(row.name)
                Text(row.agent).font(.brand(.caption2, .semibold)).foregroundStyle(Brand.muted)
                Spacer()
                Text(row.tag).font(.brand(.caption, row.failed ? .semibold : .regular)).foregroundStyle(row.failed ? Brand.accent : Brand.muted)
            }
            if let why = row.why { Text(why).font(.brand(.caption)).foregroundStyle(Brand.accent) }
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("starting.\(row.name)")
    }
}

/// What the voice read back and waits to start: its exact words, Cancel, and Start, which asks for Face ID as Approve does.
struct StartCard: View {
    let pending: NewSession.Pending
    let answer: (NewSession.Pending, Bool) async -> Void
    @State private var busy = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label { Text(NewSessionCopy.confirmTitle) } icon: { Image(systemName: "plus.circle.fill").foregroundStyle(Brand.accent) }
                .font(.brand(.headline))
            Text(Surface.shown(pending.line)).font(.brand(.subheadline)).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("startLine")
            HStack(spacing: 10) {
                Button { act(false) } label: { Text(NewSessionCopy.cancel).frame(maxWidth: .infinity) }
                    .buttonStyle(.brandQuiet).controlSize(.large)
                    .accessibilityIdentifier("startCancel")
                Button { act(true) } label: { Label(NewSessionCopy.start, systemImage: Surface.ownerSymbol).frame(maxWidth: .infinity) }
                    .buttonStyle(.brandPrimary).controlSize(.large)
                    .accessibilityIdentifier("startConfirm")
            }
            .disabled(busy)
        }
        .padding(16)
        .background(Brand.card, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.orangeLine))
        .sensoryFeedback(.warning, trigger: pending.id)
    }

    private func act(_ start: Bool) {
        busy = true
        Task { await answer(pending, start); busy = false }
    }
}

extension Demo {
    /// What the Mac would list to add: two open sessions here, one on a second machine, one from yesterday. Every name
    /// is made up.
    static let addListing = AddSessions.Listing(
        open: [AddSessions.Item(key: "-|claude-code|a1", machine: "studio", harness: "claude-code", label: "Claude Code", name: "pentest-recon",
                                folder: "pentest-notes", state: "open", ago: "5 minutes ago", branch: "recon", first: "Plan the pentest of the login service"),
               AddSessions.Item(key: "-|codex|t1", machine: "studio", harness: "codex", label: "Codex", name: "invoices", folder: "billing", state: "open",
                                ago: "just now", first: "Fix the invoice export"),
               AddSessions.Item(key: "devbox|claude-code|b2", machine: "devbox", harness: "claude-code", label: "Claude Code", name: "docs",
                                folder: "docs", state: "open", ago: "an hour ago", approvals: false)],
        recent: [AddSessions.Item(key: "-|claude-code|c3", machine: "studio", harness: "claude-code", label: "Claude Code", name: "billing-migration",
                                  folder: "billing", state: "recent", ago: "from yesterday", first: "Write the invoices migration")])

    /// What the Mac would offer: two agents that can start and one that is not installed, a second machine that cannot
    /// take a start, three folders. Every name is made up.
    static let startOptions = try? JSONDecoder().decode(NewSession.Options.self, from: Data("""
    {"harnesses": [{"name": "claude-code", "title": "Claude Code", "available": true, "why": null},
                   {"name": "opencode", "title": "OpenCode", "available": true, "why": null},
                   {"name": "codex", "title": "Codex", "available": false, "why": "Codex is not installed on this Mac."}],
     "machines": [{"name": "studio", "here": true, "available": true, "why": null},
                  {"name": "devbox", "here": false, "available": false,
                   "why": "Pointe starts sessions only on this Mac for now. On another machine, start it there and join it."}],
     "folders": [{"path": "/Users/mira/work/shop", "name": "shop", "source": "session"},
                 {"path": "/Users/mira/work/billing", "name": "billing", "source": "recent"},
                 {"path": "/Users/mira/work/lantern", "name": "lantern", "source": "added"}],
     "max_prompt": 4000}
    """.utf8))

    /// One session starting and one that did not, under the sessions; or a read-back that waits for a yes or a tap.
    static func newSessionJSON(pending: Bool) -> String {
        let starting = pending ? "[]" : """
        [{"id": "st-1", "name": "shop-2", "harness": "claude-code", "label": "Claude Code", "folder": "shop", "state": "starting", "detail": "", "since": 1700000000},
         {"id": "st-2", "name": "lantern", "harness": "codex", "label": "Codex", "folder": "lantern", "state": "failed",
          "detail": "Codex's daemon is not running.", "since": 1700000000}]
        """
        let readBack = pending ? """
        {"id": "rb-1", "line": "Start a Claude Code session in shop on studio, named shop-2? Say yes or tap.",
         "harness": "claude-code", "name": "shop-2", "folder": "shop", "expires_in": 48}
        """ : "null"
        return """
        {"active": "billing/main", "connected": true, "mode": "orchestrator", "polish": false, "hearing": "",
         "sessions": \(sessions), "talk": \(talk), "starting": \(starting), "start_pending": \(readBack)}
        """
    }
}
