import SwiftUI

private func dot(_ s: API.Session) -> Color { s.waiting || s.needs != nil ? Brand.orange : s.working ? .green : .gray }
private func state(_ s: API.Session) -> String { s.waiting ? "approve" : s.needs != nil ? "needs you" : s.working ? "working" : "idle" }

/// Waiting for you first (an approval, then a question), then working, then idle: what to look at, in order.
func byAttention(_ sessions: [API.Session]) -> [API.Session] {
    func rank(_ s: API.Session) -> Int { s.waiting ? 0 : s.needs != nil ? 1 : s.working ? 2 : 3 }
    return sessions.enumerated().sorted { (rank($0.element), $0.offset) < (rank($1.element), $1.offset) }.map(\.element)
}

/// "All" is orchestrator mode: the voice speaks for every session and none is singled out. A session chip focuses on that
/// one (session mode): everything you say goes there. Hold a chip to take it off the voice.
struct SessionChips: View {
    let sessions: [API.Session]
    let active: String?
    let mode: String?
    let focus: (String) -> Void
    let orchestrate: () -> Void
    let disconnect: (String) -> Void
    let showAll: () -> Void
    @State private var leaving: String?

    private var orchestrating: Bool { mode != "session" }

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                Button { if !orchestrating { orchestrate() } } label: {
                    Label("All", systemImage: "square.grid.2x2")
                        .font(.subheadline.weight(orchestrating ? .semibold : .regular))
                        .padding(.horizontal, 12).padding(.vertical, 8)
                        .background(orchestrating ? AnyShapeStyle(Brand.orange.opacity(0.22)) : AnyShapeStyle(.thinMaterial), in: Capsule())
                        .overlay(Capsule().stroke(orchestrating ? Brand.orange : .clear, lineWidth: 1))
                }
                .buttonStyle(.plain)
                .contextMenu {
                    Button("Sessions and mode", systemImage: "rectangle.stack", action: showAll)
                }
                .accessibilityLabel("All sessions, orchestrator mode\(orchestrating ? ", on" : "")")
                if sessions.isEmpty {
                    Text("No sessions · /pointe:voice or pointe join").font(.subheadline).foregroundStyle(.secondary)
                }
                ForEach(byAttention(sessions)) { s in
                    let on = !orchestrating && s.name == active
                    Button { if !on { focus(s.name) } } label: {
                        HStack(spacing: 7) {
                            Circle().fill(dot(s)).frame(width: 7, height: 7)
                            Text(s.name).lineLimit(1)
                            if sessions.mixesAgents { AgentBadge(session: s) }
                            if s.waiting || s.needs != nil {
                                Text(s.waiting ? "approve" : "needs you").font(.caption2.bold()).foregroundStyle(Brand.orange)
                            }
                        }
                        .font(.subheadline.weight(on ? .semibold : .regular))
                        .padding(.horizontal, 12).padding(.vertical, 8)
                        .background(on ? AnyShapeStyle(Brand.orange.opacity(0.22)) : AnyShapeStyle(.thinMaterial), in: Capsule())
                        .overlay(Capsule().stroke(on ? Brand.orange : .clear, lineWidth: 1))
                    }
                    .buttonStyle(.plain)
                    .contextMenu {
                        if !on { Button("Focus on this session", systemImage: "scope") { focus(s.name) } }
                        Button("Disconnect from the voice", systemImage: "xmark.circle", role: .destructive) { leaving = s.name }
                    }
                    .accessibilityLabel("\(s.name), \(state(s))\(on ? ", focused" : "")")
                    .accessibilityHint(on ? "" : "Focus on this session")
                }
            }
            .sensoryFeedback(.selection, trigger: (mode ?? "") + (active ?? ""))
        }
        .scrollClipDisabled()
        .confirmDisconnect($leaving, disconnect)
    }
}

/// Every session, with the routing mode. Swipe one away to disconnect it: it keeps running in its terminal.
struct SessionsSheet: View {
    let status: API.Status?
    let switchTo: (String) -> Void
    let disconnect: (String) -> Void
    let setMode: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var leaving: String?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Picker("Mode", selection: Binding(get: { status?.mode ?? "orchestrator" }, set: setMode)) {
                        Text("Orchestrator").tag("orchestrator")
                        Text("Session").tag("session")
                    }
                    .pickerStyle(.segmented)
                    .listRowBackground(Color.clear)
                } footer: {
                    Text(status?.mode == "session"
                         ? "Session: focused on \(status?.active ?? "one session"). Everything you say goes there."
                         : "Orchestrator: the voice keeps track of every session, gives you each one's status, and sends each request to the session it is about.")
                }
                Section("On the voice") {
                    if (status?.sessions ?? []).isEmpty {
                        Text("No sessions yet. Join one: /pointe:voice in Claude Code, or pointe join opencode in its folder.").foregroundStyle(.secondary)
                    }
                    ForEach(byAttention(status?.sessions ?? [])) { s in
                        Button { switchTo(s.name); dismiss() } label: {
                            HStack {
                                Circle().fill(dot(s)).frame(width: 9, height: 9)
                                Text(s.name).foregroundStyle(.primary)
                                if (status?.sessions ?? []).mixesAgents { AgentBadge(session: s) }
                                Spacer()
                                if status?.mode == "session" && s.name == status?.active {
                                    Text("focused").font(.caption.bold()).foregroundStyle(Brand.orange)
                                } else {
                                    Text(state(s)).font(.caption).foregroundStyle(.secondary)
                                }
                            }
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .swipeActions(edge: .trailing) {
                            Button("Disconnect", systemImage: "xmark.circle", role: .destructive) { leaving = s.name }
                        }
                    }
                }
                Section("Recent requests") {
                    let recent = Array((status?.recent ?? []).reversed())
                    if recent.isEmpty { Text("Each request shows here with where it went.").foregroundStyle(.secondary) }
                    ForEach(Array(recent.enumerated()), id: \.offset) { _, r in
                        VStack(alignment: .leading, spacing: 3) {
                            Text("\u{201C}\(TextDirection.isolated(r.said ?? ""))\u{201D}").lineLimit(2)
                            Text(SessionsCopy.routed(r)).font(.caption).foregroundStyle((r.to ?? []).isEmpty ? Brand.orange : .secondary)
                        }
                        .accessibilityElement(children: .combine)
                    }
                }
                if let line = SessionsCopy.context(status?.tokens) {
                    Section {
                        Text(line).font(.footnote).foregroundStyle(.secondary).accessibilityIdentifier("contextTokens")
                    } header: { Text("What the voice holds") } footer: {
                        Text("The voice model's own count, after its last reply. The messages themselves stay on your Mac: the page there shows them.")
                    }
                }
                Section {
                } footer: {
                    Text("Swipe a session to take it off the voice. It keeps running in its terminal; /pointe:voice (or pointe join) there joins it again.")
                }
            }
            .scrollContentBackground(.hidden)
            .confirmDisconnect($leaving, disconnect)
            .navigationTitle("Sessions")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}


enum SessionsCopy {
    /// "12:03:04 → billing/main (named)", or why it went nowhere, as the page's Recent requests.
    static func routed(_ r: API.Dispatch) -> String {
        let to = r.to ?? []
        let at = r.at.map { "\($0) " } ?? ""
        return to.isEmpty ? at + (r.how ?? "") : at + "→ " + to.joined(separator: " + ") + (r.how.map { " \($0)" } ?? "")
    }

    static func context(_ t: API.Tokens?) -> String? {
        guard let n = t?.context else { return nil }
        return "\(n.formatted()) tokens" + (t?.at.map { " as of \($0)" } ?? "")
    }
}

extension View {
    /// Asks before a session leaves the voice, as the page's second click does: it keeps running in its terminal.
    func confirmDisconnect(_ leaving: Binding<String?>, _ disconnect: @escaping (String) -> Void) -> some View {
        confirmationDialog("Disconnect \(leaving.wrappedValue ?? "") from the voice? It keeps running in its terminal.",
                           isPresented: Binding(get: { leaving.wrappedValue != nil }, set: { if !$0 { leaving.wrappedValue = nil } }),
                           titleVisibility: .visible, presenting: leaving.wrappedValue) { name in
            Button("Disconnect", role: .destructive) { disconnect(name) }
                .accessibilityIdentifier("confirmDisconnect")
            Button("Cancel", role: .cancel) {}
        }
    }
}

/// The coding agent behind a session, shown only when the voice mixes agents: one kind needs no label.
struct AgentBadge: View {
    let session: API.Session
    var body: some View {
        Text(session.agent)
            .font(.caption2.weight(.semibold)).foregroundStyle(.secondary)
            .padding(.horizontal, 5).padding(.vertical, 1)
            .overlay(RoundedRectangle(cornerRadius: 5).stroke(.white.opacity(0.18)))
            .accessibilityLabel("runs on \(session.agent)")
    }
}

extension Array where Element == API.Session {
    var mixesAgents: Bool { contains { ($0.harness ?? "claude-code") != "claude-code" } }
}
