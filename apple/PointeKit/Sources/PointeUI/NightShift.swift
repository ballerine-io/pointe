import SwiftUI

/// What the night shift's screens ask of the call: Face ID as for Approve, what the Mac offers (the shift, the sessions,
/// and New session's agents and folders), the start itself, and Stop.
struct NightShiftActions {
    let ownerCheck: (String) async -> Bool
    /// The running or the last shift; with an id, that one from the history.
    let load: (String?) async throws -> NightShift.Options
    let startOptions: () async throws -> NewSession.Options
    let start: (NightShift.Draft) async throws -> Void
    let stop: () async -> Void
}

/// Tasks for the sessions while you are away (docs/design/night-shift.md). Everything offered comes from the Mac; Start
/// asks for Face ID, as Approve does, and a refusal stays here in the Mac's words.
struct NightShiftSheet: View {
    static let faceIDReason = "Start the night shift"

    let actions: NightShiftActions
    var started: () -> Void = {}
    @Environment(\.dismiss) private var dismiss
    @State private var options: NightShift.Options?
    @State private var starting: NewSession.Options?
    @State private var draft = NightShift.Draft()
    @State private var problem: String?
    @State private var busy = false

    /// A row's place: a session on the voice, or a new one.
    private enum Target: Hashable { case session(String), new }

    var body: some View {
        NavigationStack {
            BrandForm {
                Section {} header: {  // a header keeps the form's text inset: a zero-inset row clipped the first letters
                    Text(NightShiftCopy.lede).brandFootnote().accessibilityIdentifier("nightShiftLede")
                }
                if let options { fields(options) }
                if let problem {
                    Section { Text(problem).foregroundStyle(Brand.accent).accessibilityIdentifier("nightShiftProblem") }
                }
            }
            .sheetTitle(NightShiftCopy.title)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(NightShiftCopy.cancel) { dismiss() }.accessibilityIdentifier("nightShiftCancel")
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(NightShiftCopy.start) { Task { await start() } }
                        .disabled(busy || options.map(draft.canStart) != true)
                        .accessibilityIdentifier("nightShiftStart")
                }
            }
            .task {
                starting = try? await actions.startOptions()  // without them a task still goes to a session on the voice
                do {
                    let fresh = try await actions.load(nil)
                    options = fresh
                    draft = NightShift.Draft(fresh, starting: starting)
                } catch { problem = Self.refusal(error) }
            }
        }
    }

    /// New session is offered in a row only when the Mac has an agent that can start and a folder to start it in.
    private var canStartNew: Bool { starting?.harnesses.contains(where: \.available) == true && starting?.folders.isEmpty == false }

    @ViewBuilder
    private func fields(_ options: NightShift.Options) -> some View {
        let sessions = options.sessions.filter(\.available)
        if sessions.isEmpty {
            Section { Text(NightShiftCopy.noSessions).foregroundStyle(Brand.muted).accessibilityIdentifier("nightShiftNoSessions") }
        }
        ForEach(Array(draft.rows.enumerated()), id: \.element.id) { index, row in
            KickerSection(NightShiftCopy.task) {
                if !sessions.isEmpty || canStartNew {
                    Picker(NightShiftCopy.session, selection: target(index)) {
                        ForEach(sessions) { Text($0.name).tag(Target.session($0.name)) }
                        if canStartNew { Text(NightShiftCopy.newSession).tag(Target.new) }
                    }
                    .pickerStyle(.menu)
                    .accessibilityIdentifier("nightShiftSession.\(index)")
                }
                if row.starts, let starting {
                    Picker(NewSessionCopy.agent, selection: $draft.rows[index].harness) {
                        ForEach(starting.harnesses.filter(\.available)) { Text($0.title).tag(Optional($0.name)) }
                    }
                    .pickerStyle(.menu)
                    .accessibilityIdentifier("nightShiftAgent.\(index)")
                    Picker(NewSessionCopy.folder, selection: $draft.rows[index].folder) {
                        ForEach(starting.folders) { Text($0.name).tag(Optional($0.path)) }
                    }
                    .pickerStyle(.menu)
                    .accessibilityIdentifier("nightShiftFolder.\(index)")
                }
                TextField(NightShiftCopy.taskPlaceholder, text: $draft.rows[index].task, axis: .vertical).lineLimit(2...6)
                    .accessibilityIdentifier("nightShiftTask.\(index)")
            }
        }
        Section {
            Button(NightShiftCopy.addTask, systemImage: "plus") { draft.addRow(options, starting: starting) }
                .buttonStyle(BrandRowButtonStyle())
                .disabled(!draft.canAdd(options))
                .accessibilityIdentifier("nightShiftAdd")
        }
        Section {
            Stepper(value: $draft.hours, in: 1...max(1, options.limits.hours), step: 1) {
                LabeledContent(NightShiftCopy.hours, value: Self.count(draft.hours))
            }
            .accessibilityIdentifier("nightShiftHours")
            Stepper(value: $draft.messages, in: 1...max(1, options.limits.messages), step: 5) {
                LabeledContent(NightShiftCopy.messages, value: "\(draft.messages)")
            }
            .accessibilityIdentifier("nightShiftMessages")
            Toggle(NightShiftCopy.notify, isOn: $draft.notify).accessibilityIdentifier("nightShiftNotify")
        } footer: {
            Group { Text(NightShiftCopy.rule).accessibilityIdentifier("nightShiftRule") }.brandFootnote()
        }
    }

    private func target(_ index: Int) -> Binding<Target> {
        Binding(get: {
            let row = draft.rows[index]
            return row.starts ? .new : .session(row.session ?? "")
        }, set: { picked in
            switch picked {
            case .new: draft.rows[index].starts = true
            case .session(let name): (draft.rows[index].starts, draft.rows[index].session) = (false, name)
            }
        })
    }

    private func start() async {
        guard let options, draft.canStart(options) else { return }
        busy = true
        defer { busy = false }
        guard await actions.ownerCheck(Self.faceIDReason) else { return }
        do {
            try await actions.start(draft)
            started()
            dismiss()
        } catch { problem = Self.refusal(error) }
    }

    /// 8, or 7.5: the hours without a ".0".
    static func count(_ hours: Double) -> String {
        hours == hours.rounded() ? "\(Int(hours))" : String(format: "%.1f", hours)
    }

    /// When a shift began, as the briefings' history says a time.
    static func when(_ at: Double) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "EEE d MMM HH:mm"
        return f.string(from: Date(timeIntervalSince1970: at))
    }

    /// A refusal in the Mac's own words; a Mac that is away, or too old for a night shift, each get a line.
    static func refusal(_ error: Error) -> String {
        guard case API.Failure.status(let code, let detail) = error else { return "The Mac did not answer." }
        if detail.hasPrefix("HTTP ") { return code == 404 ? "Pointe on the Mac has no night shift yet: update it." : "The Mac did not do it." }
        return detail
    }
}

/// On the call screen while a shift runs: how far it is, Stop, and the way to its ledger.
struct NightShiftStrip: View {
    let shift: NightShift.Summary
    let open: () -> Void
    let stop: () async -> Void
    @State private var busy = false

    var body: some View {
        HStack(spacing: 10) {
            Button(action: open) {
                HStack(spacing: 10) {
                    Image(systemName: "moon.stars.fill").foregroundStyle(Brand.accent)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(NightShiftCopy.title).font(.brand(.subheadline, .semibold))
                        Text(shift.statusLine).font(.brand(.caption)).foregroundStyle(Brand.muted)
                    }
                    Spacer(minLength: 4)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("nightShiftStrip")
            Button(NightShiftCopy.stop) {
                busy = true
                Task { await stop(); busy = false }
            }
            .buttonStyle(.brandQuiet).controlSize(.small)
            .disabled(busy)
            .accessibilityIdentifier("nightShiftStop")
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .brandCard()
    }
}

/// A night shift the voice read back and waits to start: its exact words, Cancel, and Start shift, which asks for
/// Face ID as Approve does.
struct ShiftCard: View {
    let pending: NightShift.Pending
    let answer: (NightShift.Pending, Bool) async -> Void
    @State private var busy = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label { Text(NightShiftCopy.confirmTitle) } icon: { Image(systemName: "moon.stars.fill").foregroundStyle(Brand.accent) }
                .font(.brand(.headline))
            Text(Surface.shown(pending.line)).font(.brand(.subheadline)).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("nightShiftLine")
            HStack(spacing: 10) {
                Button { act(false) } label: { Text(NightShiftCopy.cancel).frame(maxWidth: .infinity) }
                    .buttonStyle(.brandQuiet).controlSize(.large)
                    .accessibilityIdentifier("nightShiftPendingCancel")
                Button { act(true) } label: { Label(NightShiftCopy.start, systemImage: Surface.ownerSymbol).frame(maxWidth: .infinity) }
                    .buttonStyle(.brandPrimary).controlSize(.large)
                    .accessibilityIdentifier("nightShiftConfirm")
            }
            .disabled(busy)
        }
        .padding(16)
        .background(Brand.card, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.orangeLine))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("shiftCard")
        .sensoryFeedback(.warning, trigger: pending.id)
    }

    private func act(_ start: Bool) {
        busy = true
        Task { await answer(pending, start); busy = false }
    }
}

/// The ledger of the running shift, the last one, or one of the last seven: what was decided without you and what
/// waits on you first, then what was done, what is blocked and what is still going.
struct NightShiftLedger: View {
    /// The shift as the call's status has it: the ledger is read again when it moves.
    let live: NightShift.Summary?
    let actions: NightShiftActions
    @Environment(\.dismiss) private var dismiss
    @State private var page: NightShift.Options?
    @State private var loaded = false
    @State private var picked: String?  // one from the history; nil is the running or the last one
    @State private var problem: String?
    @State private var showStart: Bool

    init(live: NightShift.Summary?, actions: NightShiftActions, startOpen: Bool = false) {
        self.live = live
        self.actions = actions
        _showStart = State(initialValue: startOpen)
    }

    var body: some View {
        NavigationStack {
            BrandForm {
                if let problem {
                    Section { Text(problem).foregroundStyle(Brand.accent).accessibilityIdentifier("nightShiftLedgerProblem") }
                } else if let shift = page?.shift {
                    head(shift)
                    ForEach(shift.ledger.sections, id: \.self) { part in
                        Section { rows(part, shift.ledger) } header: {
                            Text(part.title).brandKicker().accessibilityIdentifier("nightShiftSection.\(part.rawValue)")
                        }
                    }
                } else {
                    Section { Text(loaded ? NightShiftCopy.empty : "Loading…").foregroundStyle(Brand.muted).accessibilityIdentifier("nightShiftEmpty") }
                }
                if loaded, live?.on != true {
                    Section {
                        Button(NightShiftCopy.start, systemImage: "moon.stars") { showStart = true }
                            .buttonStyle(BrandRowButtonStyle())
                            .accessibilityIdentifier("nightShiftOpenStart")
                    }
                }
                if let history = page?.history, !history.isEmpty {
                    KickerSection(NightShiftCopy.history) { ForEach(history) { past($0) } }
                }
            }
            .sheetTitle(NightShiftCopy.title)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() }.accessibilityIdentifier("nightShiftDone") } }
            .task { await reload() }
            .onChange(of: live) { Task { await reload() } }
            .sheet(isPresented: $showStart) {
                NightShiftSheet(actions: actions, started: { picked = nil })
                    .presentationDetents([.large])
                    .sheetSurface()
            }
        }
    }

    @ViewBuilder
    private func head(_ shift: NightShift.Shift) -> some View {
        KickerSection(NightShiftCopy.ledger) {
            if let headline = shift.headline {
                Text(headline).readingDirection(of: headline).font(.brand(.subheadline, .semibold))
                    .accessibilityIdentifier("nightShiftHeadline")
            }
            HStack {
                Text(shift.summary.statusLine).foregroundStyle(Brand.muted).accessibilityIdentifier("nightShiftStatus")
                Spacer()
                if shift.on {
                    Text(NightShiftCopy.running).font(.brand(.caption, .semibold)).foregroundStyle(Brand.accent)
                        .accessibilityIdentifier("nightShiftRunning")
                }
            }
            if shift.on {
                Button(NightShiftCopy.stop, systemImage: "stop.circle") { Task { await actions.stop(); await reload() } }
                    .buttonStyle(BrandRowButtonStyle())
                    .accessibilityIdentifier("nightShiftLedgerStop")
            }
        }
    }

    @ViewBuilder
    private func rows(_ part: NightShift.Section, _ ledger: NightShift.Ledger) -> some View {
        switch part {
        case .decided: ForEach(ledger.decided) { NightShiftEntryRow(part: part, entry: $0) }
        case .asked: ForEach(ledger.asked) { NightShiftEntryRow(part: part, entry: $0) }
        case .done: ForEach(ledger.done) { NightShiftEntryRow(part: part, entry: $0) }
        case .blocked: ForEach(ledger.blocked) { NightShiftEntryRow(part: part, entry: $0) }
        case .inFlight: queued(ledger.in_flight)
        case .notStarted: queued(ledger.not_started)
        }
    }

    private func queued(_ tasks: [NightShift.Queued]) -> some View {
        ForEach(Array(tasks.enumerated()), id: \.offset) { _, task in
            NightShiftTaskLine(session: task.session, task: task.task).accessibilityElement(children: .combine)
        }
    }

    /// One of the last seven: when it began and how it stands. A tap shows its ledger.
    private func past(_ shift: NightShift.Summary) -> some View {
        Button {
            picked = shift.id
            Task { await reload() }
        } label: {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(NightShiftSheet.when(shift.at)).foregroundStyle(.primary)
                    Text(shift.statusLine).font(.brand(.caption)).foregroundStyle(Brand.muted)
                }
                Spacer()
                if shift.on { Text(NightShiftCopy.running).font(.brand(.caption, .semibold)).foregroundStyle(Brand.accent) }
                if shift.id == page?.shift?.id { Image(systemName: "checkmark").font(.brand(.body, .semibold)).foregroundStyle(Brand.accent) }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(shift.id == page?.shift?.id ? .isSelected : [])
        .accessibilityIdentifier("nightShiftHistory.\(shift.id)")
    }

    private func reload() async {
        do {
            page = try await actions.load(picked)
            problem = nil
        } catch { problem = NightShiftSheet.refusal(error) }
        loaded = true
    }
}

/// Whose task it is, and the task in the person's own words.
private struct NightShiftTaskLine: View {
    let session: String
    let task: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(session).font(.brand(.footnote, .semibold))
            if !task.isEmpty { Text(task).readingDirection(of: task).font(.brand(.footnote)).foregroundStyle(Brand.muted) }
        }
    }
}

/// One line of the ledger, with what its part shows: a decision's question, choice and cost; a question; the proof of
/// what was done; what a blocker waits on, and an approval request word for word.
struct NightShiftEntryRow: View {
    let part: NightShift.Section
    let entry: NightShift.Entry

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            NightShiftTaskLine(session: entry.session, task: entry.task)
            switch part {
            case .decided:
                words(entry.question.isEmpty ? entry.text : entry.question)
                if !entry.choice.isEmpty {
                    Label(entry.choice, systemImage: "arrow.right").font(.brand(.subheadline, .semibold))
                }
                words(entry.otherwise, muted: true)
            case .done:
                words(entry.proof.isEmpty ? entry.text : entry.proof)
                let refs = [entry.commit, entry.pr].filter { !$0.isEmpty }
                if !refs.isEmpty {
                    Text(refs.joined(separator: " · ")).font(.system(.caption, design: .monospaced)).foregroundStyle(Brand.muted)
                        .textSelection(.enabled)
                }
            case .blocked:
                words(entry.text.isEmpty ? entry.waits_on : entry.text)
                if !entry.request.isEmpty {
                    Text(NightShiftCopy.exact).font(.brand(.caption, .semibold)).foregroundStyle(Brand.muted)
                    Text(entry.request).font(.system(.caption, design: .monospaced))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(8)
                        .background(Brand.raised, in: RoundedRectangle(cornerRadius: 8))
                        .accessibilityIdentifier("nightShiftRequest")
                }
            default:
                words(entry.question.isEmpty ? entry.text : entry.question)
            }
            if !entry.resolved.isEmpty {
                Text(entry.resolved).font(.brand(.caption, .semibold)).foregroundStyle(Brand.successText)
            }
        }
        .padding(.vertical, 2)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("nightShiftEntry.\(entry.id)")
    }

    @ViewBuilder
    private func words(_ text: String, muted: Bool = false) -> some View {
        if !text.isEmpty {
            Text(text).readingDirection(of: text).font(.brand(.subheadline)).foregroundStyle(muted ? Brand.muted : Brand.text)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

extension Demo {
    /// Three sessions for a night's work. Every name is made up.
    private static let shiftSessions = """
    [{"name": "billing", "working": true, "waiting": false, "needs": null, "harness": "claude-code"},
     {"name": "docs", "working": false, "waiting": false, "needs": null, "harness": "opencode"},
     {"name": "shop", "working": false, "waiting": false, "needs": null, "harness": "codex"}]
    """

    /// A shift six hours in: two tasks done, one going, one that waits for an approval, one not reached.
    private static func shiftSummary(on: Bool) -> String {
        """
        {"on": \(on), "id": "ns-3", "at": 1700000000, "ends_at": 1700028800, "ended": \(on ? "null" : "1700021600"), "why": "\(on ? "" : "stopped")",
         "sent": 9, "budget": 40, "hours": 8, "notify": false, "tasks": 5, "done": 2, "in_flight": 1, "blocked": 1, "decided": 1, "asked": 1,
         "fronts": [{"session": "billing", "harness": "claude-code", "state": "working", "task": "add the idempotency test", "done": 1, "total": 2},
                    {"session": "docs", "harness": "opencode", "state": "finished", "task": "", "done": 1, "total": 1},
                    {"session": "shop", "harness": "codex", "state": "waiting", "task": "fix the flaky test", "done": 0, "total": 2}]}
        """
    }

    /// The call with a night shift: none yet, one running (the strip), or one read back and waiting for a yes or a tap.
    static func nightShiftJSON(_ screen: Screen) -> String {
        let shift = screen == .nightShift || screen == .nightShiftLedger ? shiftSummary(on: true) : "null"
        let readBack = screen == .nightShiftPending ? """
        {"id": "sp-1", "line": "Night shift. billing: finish the retry work and open a PR. docs: update the changelog. A new Codex session in shop, named shop-2: fix the flaky test. Up to 8 hours and 40 messages. I approve nothing: a session that needs approval waits for you. Start? Say yes or tap.",
         "items": [{"session": "billing", "task": "finish the retry work and open a PR", "new": false, "agent": "Claude Code"},
                   {"session": "docs", "task": "update the changelog", "new": false, "agent": "OpenCode"},
                   {"session": "shop-2", "task": "fix the flaky test", "new": true, "agent": "Codex"}],
         "expires_in": 48}
        """ : "null"
        return """
        {"active": "billing", "connected": true, "mode": "orchestrator", "polish": false, "hearing": "",
         "sessions": \(shiftSessions), "talk": \(talk), "night_shift": \(shift), "shift_pending": \(readBack)}
        """
    }

    /// The running shift as the status carries it, for the demo's own Start.
    static var runningShift: NightShift.Summary? {
        try? JSONDecoder().decode(NightShift.Summary.self, from: Data(shiftSummary(on: true).utf8))
    }

    /// What the Mac would answer on /voice/night-shift: with `on` nil no shift was ever run; otherwise the shift above
    /// with every part of its ledger filled, and the two before it.
    static func nightShiftPage(on: Bool?) -> NightShift.Options? {
        let shift = on.map { on in
            String(shiftSummary(on: on).dropLast()) + """
            , "how": "screen",
             "ledger": {
               "decided": [{"id": "e4", "kind": "decided", "session": "billing", "task": "finish the retry work and open a PR", "at": 1700007200,
                            "question": "Retry three times or five?", "choice": "Three, with backoff.",
                            "otherwise": "Five means raising the timeout budget in the config."}],
               "asked": [{"id": "e5", "kind": "asked", "session": "docs", "task": "update the changelog", "at": 1700009000,
                          "question": "Should the changelog list internal refactors?", "text": "Left to the session."}],
               "done": [{"id": "e1", "kind": "done", "session": "billing", "task": "finish the retry work and open a PR", "at": 1700010800,
                         "proof": "Retries back off; 42 tests pass.", "commit": "3f9c2ab", "pr": "#128"},
                        {"id": "e2", "kind": "done", "session": "docs", "task": "update the changelog", "at": 1700012000,
                         "proof": "The changelog has the retry fix and the new timeout."}],
               "blocked": [{"id": "e3", "kind": "blocked", "session": "shop", "task": "fix the flaky test", "at": 1700014400,
                            "text": "shop waits for your approval.", "waits_on": "you",
                            "request": "Bash: Push the branch\\n{\\"command\\": \\"git push origin fix-flaky-test\\"}", "request_id": "ab12cd34"}],
               "in_flight": [{"session": "billing", "task": "add the idempotency test", "since": 1700015000, "followups": 1}],
               "not_started": [{"session": "shop", "task": "update the README"}]},
             "morning": [{"kind": "headline", "title": "", "text": "Six hours in: 2 of 5 tasks done, 1 blocked."}]}
            """
        } ?? "null"
        let history = on.map { on in
            """
            [\(shiftSummary(on: on)),
             {"on": false, "id": "ns-2", "at": 1699913600, "ends_at": 1699942400, "ended": 1699930000, "why": "complete", "sent": 12, "budget": 40,
              "hours": 8, "notify": false, "tasks": 4, "done": 4, "in_flight": 0, "blocked": 0, "decided": 2, "asked": 0, "fronts": []},
             {"on": false, "id": "ns-1", "at": 1699827200, "ends_at": 1699856000, "ended": 1699840000, "why": "stopped", "sent": 5, "budget": 40,
              "hours": 8, "notify": false, "tasks": 3, "done": 1, "in_flight": 0, "blocked": 1, "decided": 0, "asked": 1, "fronts": []}]
            """
        } ?? "[]"
        let json = """
        {"shift": \(shift), "history": \(history), "caps": {"hours": 8.0, "messages": 40, "notify": false},
         "limits": {"hours": 12.0, "messages": 200, "sessions": 8, "tasks": 5, "task_chars": 2000, "followups": 3},
         "rule": "I approve nothing: a session that needs approval waits for you.", "pending": null,
         "sessions": [{"name": "billing", "harness": "claude-code", "available": true, "why": null},
                      {"name": "docs", "harness": "opencode", "available": true, "why": null},
                      {"name": "shop", "harness": "codex", "available": true, "why": null}]}
        """
        return try? JSONDecoder().decode(NightShift.Options.self, from: Data(json.utf8))
    }
}
