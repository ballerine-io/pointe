import SwiftUI

private func dot(_ s: API.Session) -> Color { s.isOffline ? Brand.raised2 : s.waiting || s.needs != nil ? Brand.orange : s.working ? Brand.success : Brand.raised2 }
private func state(_ s: API.Session) -> String {
    s.isOffline ? "offline" : s.waiting ? "approve" : s.needs != nil ? "needs you" : s.working ? "working" : "idle"
}

/// Waiting for you first (an approval, then a question), then working, then idle: what to look at, in order.
func byAttention(_ sessions: [API.Session]) -> [API.Session] {
    func rank(_ s: API.Session) -> Int { s.waiting ? 0 : s.needs != nil ? 1 : s.working ? 2 : 3 }
    return sessions.enumerated().sorted { (rank($0.element), $0.offset) < (rank($1.element), $1.offset) }.map(\.element)
}

/// "All" is orchestrator mode: the voice speaks for every session and none is singled out. A session chip focuses on that
/// one (session mode): everything you say goes there. Hold a chip to take it off the voice. One row: with more than one
/// machine the chips are grouped by machine, each group behind a small divider that names it; the machine filter itself
/// is in the Sessions sheet.
struct SessionChips: View {
    let sessions: [API.Session]
    var known = true  // false until the Mac has answered once: "No sessions" would be a guess
    /// Sessions Pointe is starting (a spoken "start a new session" and its yes), shown at once, first after All, before
    /// they join: at the end of a long strip they would be out of sight.
    var starting: [NewSession.Starting] = []
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
        strip
    }

    /// The strip's groups: one per machine that has sessions to show (the filter narrows it to one), or one unnamed group.
    private var groups: [(machine: String?, sessions: [API.Session])] {
        guard machines.multi else { return [(nil, byAttention(sessions))] }
        let shown = machines.valid(filter.wrappedValue).map { [$0] } ?? machines.names
        return shown.map { ($0, byAttention(machines.onMachine($0))) }.filter { !$0.sessions.isEmpty }
    }

    /// "devbox" before its chips: a dot (filled while online) and the name, quiet, not a button.
    private func divider(_ name: String) -> some View {
        HStack(spacing: 5) {
            Circle().fill(machines.isOffline(name) ? Color.clear : Brand.success)
                .overlay(Circle().stroke(machines.isOffline(name) ? Brand.dim : Color.clear))
                .frame(width: 5, height: 5)
            Text(name).font(.brand(.caption2, .semibold)).kerning(0.6).textCase(.uppercase).foregroundStyle(Brand.dim)
        }
        .padding(.leading, 6)
        .environment(\.layoutDirection, .leftToRight)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Sessions on \(name)\(machines.isOffline(name) ? ", offline" : "")")
        .accessibilityIdentifier("machineDivider.\(name)")
    }

    private var strip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                Button { if !orchestrating { orchestrate() } } label: {
                    Label("All", systemImage: "square.grid.2x2")
                        .font(.brand(.subheadline, orchestrating ? .semibold : .regular))
                        .padding(.horizontal, 12).padding(.vertical, 8)
                        .background(orchestrating ? AnyShapeStyle(Brand.tint) : AnyShapeStyle(Brand.raised), in: Capsule())
                        .overlay(Capsule().stroke(orchestrating ? Brand.orangeLine : Brand.line, lineWidth: 1))
                        .touchTarget(height: 34)
                }
                .buttonStyle(.plain)
                .contextMenu {
                    Button("Sessions and mode", systemImage: "rectangle.stack", action: showAll)
                }
                .accessibilityLabel("All sessions, orchestrator mode\(orchestrating ? ", on" : "")")
                ForEach(starting) { row in
                    HStack(spacing: 7) {
                        Circle().stroke(Brand.dim).frame(width: 7, height: 7)  // a ring: not a session yet
                        Text(row.name).lineLimit(1).truncationMode(.middle).frame(maxWidth: 220)
                        Text(row.tag).font(.brand(.caption2, row.failed ? .semibold : .regular))
                            .foregroundStyle(row.failed ? Brand.accent : Brand.muted)
                    }
                    .font(.brand(.subheadline))
                    .padding(.horizontal, 12).padding(.vertical, 8)
                    .background(Brand.raised, in: Capsule())
                    .overlay(Capsule().stroke(Brand.line, style: StrokeStyle(lineWidth: 1, dash: [3, 3])))
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel("\(row.name), \(row.agent), \(row.tag)")
                    .accessibilityIdentifier("startingChip.\(row.name)")
                }
                if sessions.isEmpty && starting.isEmpty && known {
                    Text("No sessions yet").font(.brand(.subheadline)).foregroundStyle(Brand.muted)  // how to join is the line under it: said once
                }
                ForEach(groups, id: \.machine) { group in
                  if let name = group.machine { divider(name) }
                  ForEach(group.sessions) { s in
                    let on = !orchestrating && s.name == active
                    let machine = machines.of(s)
                    Button { if !on { focus(s.name) } } label: {
                        HStack(spacing: 7) {
                            Circle().fill(dot(s)).frame(width: 7, height: 7)
                            Text(s.name).lineLimit(1).truncationMode(.middle).frame(maxWidth: 220)  // a branch-long name keeps both ends, and the next chip stays in reach
                            HarnessMark(harness: s.harness)
                            if s.isOffline {
                                Text("offline").font(.brand(.caption2)).foregroundStyle(Brand.muted)
                            } else if s.waiting || s.needs != nil {
                                Text(s.waiting ? "approve" : "needs you").font(.brand(.caption2, .semibold)).foregroundStyle(Brand.accent)
                            }
                        }
                        .opacity(s.isOffline ? 0.45 : 1)
                        .font(.brand(.subheadline, on ? .semibold : .regular))
                        .padding(.horizontal, 12).padding(.vertical, 8)
                        .background(on ? AnyShapeStyle(Brand.tint) : AnyShapeStyle(Brand.raised), in: Capsule())
                        .overlay(Capsule().stroke(on ? Brand.orangeLine : Brand.line, lineWidth: 1))
                        .touchTarget(height: 34)
                    }
                    .buttonStyle(.plain)
                    .hoverLift()
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
            }
            .sensoryFeedback(.selection, trigger: (mode ?? "") + (active ?? ""))
            .padding(.vertical, 5)  // the chips' 44-point touch inside the scroll view's bounds: a touch outside them is lost
        }
        .padding(.vertical, -5)  // and the strip laid out at what the chips draw, as before
        .scrollClipDisabled()
        .edgeFade()
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
    /// All · studio · devbox: which machine's sessions show, here and in the strip behind. A view only: nothing is sent.
    var filter: Binding<String?> = .constant(nil)
    /// Starting a new session from here; nil hides the button.
    var starter: NewSessionActions? = nil
    /// Adding sessions already open, or reopening one from this week; nil hides the button.
    var adder: AddSessionsActions? = nil
    /// The Mac's wide window: this list is the window's left column (the page's), always there, not a sheet.
    var docked: Docked? = nil
    @Environment(\.dismiss) private var dismiss
    @Environment(\.dynamicTypeSize) private var typeSize
    @State private var leaving: String?
    @State private var showNewSession = false
    @State private var showAddSessions = false
    @State private var renaming: String?
    @State private var newName = ""

    struct Docked {
        let settings: () -> Void
        let rename: (String, String) -> Void
    }

    private var machines: MachineView { MachineView(status) }

    private func foot<Style: LabelStyle>(_ docked: Docked, _ style: Style) -> some View {
        HStack(spacing: 8) {
            if starter != nil {
                Button { showNewSession = true } label: { Label(NewSessionCopy.title, systemImage: "plus") }
                    .buttonStyle(.brandQuiet).controlSize(.small).help(NewSessionCopy.title).accessibilityIdentifier("newSession")
            }
            if adder != nil {
                Button { showAddSessions = true } label: { Label(AddSessionsCopy.title, systemImage: "rectangle.stack.badge.plus") }
                    .buttonStyle(.brandQuiet).controlSize(.small).help(AddSessionsCopy.title).accessibilityIdentifier("addSessions")
            }
            Spacer(minLength: 0)
            Button(action: docked.settings) { Label("Settings", systemImage: "gearshape") }
                .buttonStyle(.brandQuiet).controlSize(.small).help("Settings").accessibilityIdentifier("sideSettings")
        }
        .labelStyle(style)
        .lineLimit(1)
        .fixedSize(horizontal: false, vertical: true)
    }

    var body: some View {
        if let docked {
            VStack(spacing: 0) {
                list.accessibilityElement(children: .contain).accessibilityIdentifier("sessionsColumn")
                // The page's foot of the column: New session, Add sessions and Settings, with their words while the
                // column has room for them on one line, else as their symbols (named on hover): a narrow column broke
                // the words inside themselves ("sessi/on").
                ViewThatFits(in: .horizontal) {
                    foot(docked, .titleAndIcon)
                    foot(docked, .iconOnly)
                }
                .padding(12)
                .overlay(alignment: .top) { Rectangle().fill(Brand.line).frame(height: 1) }
            }
            .background(Brand.surface.ignoresSafeArea())
            .confirmDisconnect($leaving, disconnect)
            .sheet(isPresented: $showNewSession) { if let starter { NewSessionSheet(actions: starter).sheetSurface() } }
            .sheet(isPresented: $showAddSessions) { if let adder { AddSessionsSheet(actions: adder).sheetSurface() } }
            .alert("Rename \(renaming ?? "")", isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } })) {
                TextField("Name", text: $newName)
                Button("Rename") {
                    let fresh = newName.trimmingCharacters(in: .whitespaces)
                    if let old = renaming, !fresh.isEmpty, fresh != old { docked.rename(old, fresh) }
                    renaming = nil
                }
                Button("Cancel", role: .cancel) { renaming = nil }
            } message: { Text(SessionsCopy.renameHelp) }
        } else {
            sheet
        }
    }

    private var sheet: some View {
        NavigationStack {
            list
            .scrollContentBackground(.hidden)
            .confirmDisconnect($leaving, disconnect)
            .sheetTitle("Sessions")
            .toolbar {
                if starter != nil {
                    ToolbarItem(placement: .sheetLeading) {
                        Button(NewSessionCopy.title) { showNewSession = true }.accessibilityIdentifier("newSession")
                    }
                }
                if adder != nil {
                    ToolbarItem(placement: .sheetLeading) {
                        Button(AddSessionsCopy.title) { showAddSessions = true }.accessibilityIdentifier("addSessions")
                    }
                }
                ToolbarItem(placement: .sheetDone) { Button("Done") { dismiss() } }
            }
            .sheet(isPresented: $showNewSession) {
                if let starter {
                    NewSessionSheet(actions: starter)
                        .presentationDetents([.large])
                        .sheetSurface()
                }
            }
            .sheet(isPresented: $showAddSessions) {
                if let adder {
                    AddSessionsSheet(actions: adder)
                        .presentationDetents([.large])
                        .sheetSurface()
                }
            }
        }
    }

    private var list: some View {
            BrandList {
                Section {
                    Segments(selection: Binding(get: { status?.mode ?? "orchestrator" }, set: setMode),
                             options: [("orchestrator", "Orchestrator"), ("session", "Session")]) {
                    Picker("Mode", selection: Binding(get: { status?.mode ?? "orchestrator" }, set: setMode)) {
                        Text("Orchestrator").tag("orchestrator")
                        Text("Session").tag("session")
                    }
                    .pickerStyle(.segmented)
                    }
                    .accessibilityIdentifier("modePicker")
                    .listRowBackground(Color.clear).listRowInsets(EdgeInsets())  // edge to edge with the cards below
                } footer: {
                    Group {
                        Text(status?.mode == "session"
                             ? "Session: focused on \(status?.active ?? "one session"). Everything you say goes there."
                             : "Orchestrator: the voice keeps track of every session, gives you each one's status, and sends each request to the session it is about.")
                    }.brandFootnote()
                }
                if machines.multi {
                    Section {
                        MachineFilter(machines: machines, filter: filter)
                            .listRowBackground(Color.clear).listRowInsets(EdgeInsets())
                    }
                    ForEach((machines.valid(filter.wrappedValue).map { [$0] } ?? machines.names).sorted { $0 == section && $1 != section }, id: \.self) { name in
                        Section {
                            rows(machines.onMachine(name))
                            if name == machines.here { startingRows }  // a start always runs on this Mac
                        } header: {
                            Group {
                                HStack(spacing: 6) {  // a small dot: filled while the machine is online, a ring while it is not
                                    Circle().fill(machines.isOffline(name) ? Color.clear : Brand.success)
                                        .overlay(Circle().stroke(machines.isOffline(name) ? Brand.dim : Color.clear))
                                        .frame(width: 6, height: 6).accessibilityHidden(true)
                                    Text(machines.header(name))
                                        .foregroundStyle(machines.isOffline(name) ? Brand.accent : Brand.muted)
                                        .accessibilityIdentifier("machineSection.\(name)")
                                }
                            }.brandFootnote()
                        }
                        .opacity(machines.isOffline(name) ? 0.6 : 1)
                    }
                } else {
                    KickerSection("On the voice") {
                        if (status?.sessions ?? []).isEmpty {
                            Text("No sessions yet. Join one: /pointe:voice in Claude Code, or pointe join opencode in its folder.".unbrokenCommands).foregroundStyle(Brand.muted)
                        }
                        rows(status?.sessions ?? [])
                        startingRows
                    }
                }
                recentAndContext
            }
    }

    /// Sessions Pointe is starting, or that did not start: under the sessions, with no actions.
    private var startingRows: some View {
        ForEach(status?.starting ?? []) { StartingRow(row: $0) }
    }

    @ViewBuilder
    private func rows(_ sessions: [API.Session]) -> some View {
        ForEach(byAttention(sessions)) { s in
            Button { switchTo(s.name); if docked == nil { dismiss() } } label: {
                // One line while it fits; in a narrow column (the Mac's sidebar) the state goes under the name, and a
                // name longer than the column loses its middle, never breaking inside a word.
                ViewThatFits(in: .horizontal) {
                    HStack {
                        name(s)
                        Spacer()
                        rowState(s)
                    }
                    VStack(alignment: .leading, spacing: 2) {
                        name(s)
                        rowState(s).padding(.leading, 17)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .hoverLift()
            .accessibilityIdentifier("session.\(s.name)")
            .swipeActions(edge: .trailing) {
                Button("Disconnect", systemImage: "xmark.circle", role: .destructive) { leaving = s.name }
            }
            .contextMenu {  // a pointer has no swipe: the same actions as a session's chip
                Button("Focus on this session", systemImage: "scope") { switchTo(s.name); if docked == nil { dismiss() } }
                if docked != nil { Button("Rename", systemImage: "pencil") { newName = s.name; renaming = s.name } }
                Button("Disconnect from the voice", systemImage: "xmark.circle", role: .destructive) { leaving = s.name }
            }
            .opacity(s.isOffline ? 0.5 : 1)
        }
    }

    private func name(_ s: API.Session) -> some View {
        HStack {
            Circle().fill(dot(s)).frame(width: 9, height: 9)
            Text(s.name).foregroundStyle(.primary).lineLimit(typeSize.isAccessibilitySize ? 3 : 1).truncationMode(.middle).help(s.name)
            HarnessMark(harness: s.harness)
        }
    }

    @ViewBuilder
    private func rowState(_ s: API.Session) -> some View {
        if s.isOffline {
            Text("offline since \(MachinesCopy.since(machines.info(machines.of(s))?.since))")
                .font(.brand(.caption)).foregroundStyle(Brand.muted)
        } else if status?.mode == "session" && s.name == status?.active {
            Text("focused").font(.brand(.caption, .semibold)).foregroundStyle(Brand.accent)
        } else {
            Text(state(s)).font(.brand(.caption)).foregroundStyle(Brand.muted)
        }
    }

    @ViewBuilder
    private var recentAndContext: some View {
        KickerSection("Recent requests") {
            let recent = Array((status?.recent ?? []).reversed())
            if recent.isEmpty { Text("Each request shows here with where it went.").foregroundStyle(Brand.muted) }
            ForEach(Array(recent.enumerated()), id: \.offset) { _, r in
                VStack(alignment: .leading, spacing: 3) {
                    Text("\u{201C}\(TextDirection.isolated(r.said ?? ""))\u{201D}").lineLimit(2)
                    Text(SessionsCopy.routed(r)).font(.brand(.caption)).foregroundStyle((r.to ?? []).isEmpty ? Brand.accent : Brand.muted)
                }
                .accessibilityElement(children: .combine)
            }
        }
        if let line = SessionsCopy.context(status?.tokens) {
            Section {
                Text(line).font(.brand(.footnote)).foregroundStyle(Brand.muted).accessibilityIdentifier("contextTokens")
            } header: { Group { Text("What the voice holds") }.brandKicker() } footer: {
                Group {
                    Text("The voice model's own count, after its last reply. The messages themselves stay on your Mac: the page there shows them.")
                }.brandFootnote()
            }
        }
        Section {
        } footer: {
            Group {
                Text("\(Surface.isMac ? "Right-click" : "Swipe") a session to take it off the voice. It keeps running in its terminal; /pointe:voice (or pointe join) there joins it again.".unbrokenCommands)
            }.brandFootnote()
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
            .font(.brand(.caption2, .semibold)).foregroundStyle(Brand.muted)
            .padding(.horizontal, 5).padding(.vertical, 1)
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Brand.line))
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
    /// The sessions that wait for you (a request, or a question): the call screen's "· 2 need you", the widget's count.
    func needingYou(_ filter: String? = nil) -> Int {
        shown(filter).filter { ($0.waiting || $0.needs != nil) && !$0.isOffline }.count
    }
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

    /// "The invite was cancelled after 20 wrong codes, from …." while no new invite is out; nil otherwise.
    static func ended(_ status: API.Status?) -> String? {
        guard status?.invite == nil, let why = status?.invite_ended, let first = why.first else { return nil }
        return first.uppercased() + why.dropFirst() + "."
    }
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
    static func joinLine(_ invite: API.Invite, pairing: Pairing?) -> String {
        if let link = invite.link, !link.isEmpty { return "pointe node join '\(link)'" }
        guard let pairing else { return "pointe node join \(invite.code)" }  // the Mac app, and a daemon too old to send the line
        var c = URLComponents()
        c.scheme = "pointe"; c.host = "hub"
        c.queryItems = [.init(name: "v", value: "1"), .init(name: "host", value: pairing.host),
                        .init(name: "port", value: String(pairing.port)), .init(name: "fp", value: pairing.fingerprint),
                        .init(name: "code", value: invite.code)]
        return "pointe node join '\(c.string ?? "")'"
    }
}

/// All · studio · devbox, at the top of the Sessions sheet: which machine's sessions the sheet and the strip show. One
/// tap, nothing sent.
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
            Text(label).font(.brand(.caption, on ? .semibold : .regular))
                .padding(.horizontal, 12).padding(.vertical, 7)
                .background(on ? AnyShapeStyle(Brand.tint) : AnyShapeStyle(Brand.raised), in: Capsule())
                .overlay(Capsule().stroke(on ? Brand.orangeLine : Brand.line, lineWidth: 1))
                .opacity(away ? 0.5 : 1)
                .touchTarget(height: 30)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("machineChip.\(name ?? "all")")
        .accessibilityLabel(name == nil ? "All machines" : "\(label)\(away ? ", offline" : "")")
        .accessibilityValue(on ? "selected" : "")
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}
