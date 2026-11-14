import SwiftUI

private func dot(_ s: API.Session) -> Color { s.isOffline ? .gray : s.waiting || s.needs != nil ? Brand.orange : s.working ? .green : .gray }
private func state(_ s: API.Session) -> String {
    s.isOffline ? "offline" : s.waiting ? "approve" : s.needs != nil ? "needs you" : s.working ? "working" : "idle"
}

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
    var rename: ((String, String) -> Void)? = nil
    var machines = MachineView(nil)
    var filter: Binding<String?> = .constant(nil)
    /// Opens the Sessions sheet on that machine's section.
    var showMachine: ((String) -> Void)? = nil
    @State private var leaving: String?
    @State private var renaming: String?
    @State private var newName = ""

    private var orchestrating: Bool { mode != "session" }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if machines.multi { MachineFilter(machines: machines, filter: filter) }
            strip
        }
    }

    private var strip: some View {
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
                ForEach(byAttention(machines.multi ? machines.shown(filter.wrappedValue) : sessions)) { s in
                    let on = !orchestrating && s.name == active
                    let machine = machines.of(s)
                    Button { if !on { focus(s.name) } } label: {
                        HStack(spacing: 7) {
                            Circle().fill(dot(s)).frame(width: 7, height: 7)
                            Text(s.name).lineLimit(1)
                            if sessions.mixesAgents { AgentBadge(session: s) }
                            if machines.mixed && machines.valid(filter.wrappedValue) == nil { MachineBadge(name: machine) }
                            if s.isOffline {
                                Text("offline").font(.caption2).foregroundStyle(.secondary)
                            } else if s.waiting || s.needs != nil {
                                Text(s.waiting ? "approve" : "needs you").font(.caption2.bold()).foregroundStyle(Brand.orange)
                            }
                        }
                        .opacity(s.isOffline ? 0.45 : 1)
                        .font(.subheadline.weight(on ? .semibold : .regular))
                        .padding(.horizontal, 12).padding(.vertical, 8)
                        .background(on ? AnyShapeStyle(Brand.orange.opacity(0.22)) : AnyShapeStyle(.thinMaterial), in: Capsule())
                        .overlay(Capsule().stroke(on ? Brand.orange : .clear, lineWidth: 1))
                    }
                    .buttonStyle(.plain)
                    .contextMenu {
                        if !on { Button("Focus on this session", systemImage: "scope") { focus(s.name) } }
                        if rename != nil {
                            Button("Rename", systemImage: "pencil") { newName = s.name; renaming = s.name }
                        }
                        if machines.multi, let showMachine {
                            Button("Sessions on \(machine)", systemImage: "desktopcomputer") { showMachine(machine) }
                        }
                        Button("Disconnect from the voice", systemImage: "xmark.circle", role: .destructive) { leaving = s.name }
                    }
                    .accessibilityLabel("\(s.name)\(machines.mixed ? ", on \(machine)" : ""), \(state(s))\(on ? ", focused" : "")")
                    .accessibilityHint(on ? "" : "Focus on this session")
                }
            }
            .sensoryFeedback(.selection, trigger: (mode ?? "") + (active ?? ""))
        }
        .scrollClipDisabled()
        .confirmDisconnect($leaving, disconnect)
        .alert("Rename \(renaming ?? "")", isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } })) {
            TextField("Name", text: $newName)
            Button("Rename") {
                let fresh = newName.trimmingCharacters(in: .whitespaces)
                if let old = renaming, !fresh.isEmpty, fresh != old { rename?(old, fresh) }
                renaming = nil
            }
            Button("Cancel", role: .cancel) { renaming = nil }
        } message: { Text(SessionsCopy.renameHelp) }
    }
}

/// Every session, with the routing mode. Swipe one away to disconnect it: it keeps running in its terminal.
struct SessionsSheet: View {
    let status: API.Status?
    let switchTo: (String) -> Void
    let disconnect: (String) -> Void
    let setMode: (String) -> Void
    /// The machine to open on (a chip's "Sessions on devbox"): its section comes first.
    var section: String? = nil
    @Environment(\.dismiss) private var dismiss
    @State private var leaving: String?

    private var machines: MachineView { MachineView(status) }

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
                if machines.multi {
                    ForEach(machines.names.sorted { $0 == section && $1 != section }, id: \.self) { name in
                        Section {
                            rows(machines.onMachine(name))
                        } header: {
                            Text(machines.header(name))
                                .foregroundStyle(machines.isOffline(name) ? Brand.orange : .secondary)
                                .accessibilityIdentifier("machineSection.\(name)")
                        }
                        .opacity(machines.isOffline(name) ? 0.6 : 1)
                    }
                } else {
                    Section("On the voice") {
                        if (status?.sessions ?? []).isEmpty {
                            Text("No sessions yet. Join one: /pointe:voice in Claude Code, or pointe join opencode in its folder.").foregroundStyle(.secondary)
                        }
                        rows(status?.sessions ?? [])
                    }
                }
                recentAndContext
            }
            .scrollContentBackground(.hidden)
            .confirmDisconnect($leaving, disconnect)
            .navigationTitle("Sessions")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }

    @ViewBuilder
    private func rows(_ sessions: [API.Session]) -> some View {
        ForEach(byAttention(sessions)) { s in
            Button { switchTo(s.name); dismiss() } label: {
                HStack {
                    Circle().fill(dot(s)).frame(width: 9, height: 9)
                    Text(s.name).foregroundStyle(.primary)
                    if (status?.sessions ?? []).mixesAgents { AgentBadge(session: s) }
                    Spacer()
                    if s.isOffline {
                        Text("offline since \(MachinesCopy.since(machines.info(machines.of(s))?.since))")
                            .font(.caption).foregroundStyle(.secondary)
                    } else if status?.mode == "session" && s.name == status?.active {
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
            .opacity(s.isOffline ? 0.5 : 1)
        }
    }

    @ViewBuilder
    private var recentAndContext: some View {
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
}


enum SessionsCopy {
    static let renameHelp = "A name you can say: letters, digits, spaces, dots, slashes or dashes."

    /// The Mac's refusal of a rename (taken, not a name voice can pick), as a sentence.
    static func renameRefused(_ detail: String) -> String {
        let d = detail.trimmingCharacters(in: .whitespaces)
        if d.isEmpty || d.hasPrefix("HTTP ") { return "Not renamed: the Mac did not answer." }
        let said = CallView.sentence(d)
        return "Not renamed: \(said.prefix(1).lowercased())\(said.dropFirst())"
    }

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

// MARK: machines (docs/multi-machine.md)

/// Which machine each session runs on, as the page shows it. With one machine every answer here is "as before". The
/// machine filter is a view only: it sends nothing and changes no mode. Pure, so it is unit tested.
struct MachineView: Equatable {
    let here: String                // this Mac's name; empty from a Mac without machines
    let names: [String]             // this Mac first, then the paired machines, then any a session names
    let machines: [API.Machine]
    let sessions: [API.Session]

    init(_ status: API.Status?) {
        machines = status?.machines ?? []
        sessions = status?.sessions ?? []
        let here = machines.first(where: \.isHere)?.name ?? ""
        self.here = here
        var names: [String] = []
        for n in [here] + machines.filter { !$0.isHere }.map(\.name) + sessions.map({ Self.of($0, here: here) })
        where !n.isEmpty && !names.contains(n) { names.append(n) }
        self.names = names
    }

    private static func of(_ s: API.Session, here: String) -> String { (s.machine ?? "").isEmpty ? here : s.machine! }
    func of(_ s: API.Session) -> String { Self.of(s, here: here) }
    func info(_ name: String) -> API.Machine? { machines.first { $0.name == name } }
    func isOffline(_ name: String) -> Bool { info(name)?.isOffline == true }

    /// Groups, chips and filter only once there is a second machine.
    var multi: Bool { names.count > 1 }
    /// More than one machine has sessions: each session says where it runs.
    var mixed: Bool { Set(sessions.map(of)).count > 1 }
    /// A filter on a machine that is gone (revoked) falls back to All.
    func valid(_ filter: String?) -> String? { multi && filter.map(names.contains) == true ? filter : nil }
    func shown(_ filter: String?) -> [API.Session] {
        guard let f = valid(filter) else { return sessions }
        return sessions.filter { of($0) == f }
    }
    func onMachine(_ name: String) -> [API.Session] { sessions.filter { of($0) == name } }

    /// "shop · devbox" where the machine needs saying; a name suffixed with its machine ("shop devbox", the second shop
    /// to join) drops the suffix here.
    func label(_ s: API.Session) -> String {
        let m = of(s), remote = m != here
        guard mixed || remote, !m.isEmpty else { return s.name }
        let base = remote && s.name.hasSuffix(" " + m) ? String(s.name.dropLast(m.count + 1)) : s.name
        return "\(base) · \(m)"
    }

    /// "devbox · Linux · 23 ms", "laptop · macOS · offline since 14:02", "studio · this Mac".
    func header(_ name: String, now: Date = Date()) -> String {
        guard let m = info(name) else { return name }
        if m.isHere { return "\(name) · this Mac" }
        let state = m.isOffline ? "offline since \(MachinesCopy.since(m.since, now: now))" : m.rtt_ms.map { "\($0) ms" } ?? "online"
        return [name, m.osName, state].filter { !$0.isEmpty }.joined(separator: " · ")
    }
}

enum MachinesCopy {
    static let title = "Machines"
    static let invite = "Invite a machine"
    static let inviteReason = "Show a code that pairs another machine with this voice"
    static let revokeReason = "Revoke a machine"
    static let help = "Sessions on your other Macs and Linux machines join this voice through a small Pointe there. Their "
        + "transcripts, with credentials masked, come to your Mac and go to the same services as its own."
    static let codeHelp = "On the other machine, run pointe node join with this code. It works once."
    static let offlineCard = "offline: answer it in its terminal"
    static func revokeAsk(_ name: String) -> String {
        "Revoke \(name)? Its sessions leave the voice, and it needs a new code to come back."
    }

    /// "14:02" today, "Mon 14:02" before; "a while" when the Mac did not say.
    static func since(_ t: Double?, now: Date = Date()) -> String {
        guard let t else { return "a while" }
        let d = Date(timeIntervalSince1970: t), f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = Calendar.current.isDate(d, inSameDayAs: now) ? "HH:mm" : "EEE HH:mm"
        return f.string(from: d)
    }

    /// "9:58" left on a code; nil once it lapsed.
    static func countdown(_ seconds: Double) -> String? {
        let s = Int(seconds.rounded(.down))
        return s > 0 ? "\(s / 60):\(String(format: "%02d", s % 60))" : nil
    }

    /// The line the other machine pastes: the host, port and fingerprint this phone paired with, and the code.
    static func joinLine(_ invite: API.Invite, pairing: Pairing) -> String {
        if let link = invite.link, !link.isEmpty { return "pointe node join '\(link)'" }
        var c = URLComponents()
        c.scheme = "pointe"; c.host = "hub"
        c.queryItems = [.init(name: "v", value: "1"), .init(name: "host", value: pairing.host),
                        .init(name: "port", value: String(pairing.port)), .init(name: "fp", value: pairing.fingerprint),
                        .init(name: "code", value: invite.code)]
        return "pointe node join '\(c.string ?? "")'"
    }
}

/// The machine a session runs on, shown only when more than one machine has sessions.
struct MachineBadge: View {
    let name: String
    var body: some View {
        Text(name)
            .font(.caption2.weight(.semibold)).foregroundStyle(.secondary)
            .padding(.horizontal, 5).padding(.vertical, 1)
            .overlay(RoundedRectangle(cornerRadius: 5).stroke(.white.opacity(0.18)))
            .environment(\.layoutDirection, .leftToRight)
            .accessibilityLabel("on \(name)")
    }
}

/// All · studio · devbox: which machine's sessions the strip and the sheet show. One tap, nothing sent.
struct MachineFilter: View {
    let machines: MachineView
    @Binding var filter: String?

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                chip(nil, "All")
                ForEach(machines.names, id: \.self) { chip($0, $0) }
            }
        }
        .scrollClipDisabled()
        .sensoryFeedback(.selection, trigger: filter ?? "")
    }

    private func chip(_ name: String?, _ label: String) -> some View {
        let on = machines.valid(filter) == name
        let away = name.map(machines.isOffline) == true
        return Button { filter = name } label: {
            Text(label).font(.caption.weight(on ? .semibold : .regular))
                .padding(.horizontal, 10).padding(.vertical, 5)
                .background(on ? AnyShapeStyle(Brand.orange.opacity(0.22)) : AnyShapeStyle(.thinMaterial), in: Capsule())
                .overlay(Capsule().stroke(on ? Brand.orange : .clear, lineWidth: 1))
                .opacity(away ? 0.5 : 1)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("machineChip.\(name ?? "all")")
        .accessibilityLabel(name == nil ? "All machines" : "\(label)\(away ? ", offline" : "")")
        .accessibilityValue(on ? "selected" : "")
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}
