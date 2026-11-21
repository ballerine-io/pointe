import PointeKit
import PointeMacKit
import SwiftUI

/// The brand's colours (assets/theme.json through PointeKit). Text uses the system font: this is a Mac window.
enum Brand {
    static let card = Color(BrandToken.card)
    static let raised = Color(BrandToken.raised)
    static let muted = Color(BrandToken.muted)
    static let line = Color(BrandToken.line)
    static let lineStrong = Color(BrandToken.lineStrong)
    static let orange = Color(BrandToken.orange)
    static let onOrange = Color(BrandToken.onOrange)
    static let accent = Color(BrandToken.accent)
    static let tint = Color(BrandToken.tint)
    static let orangeLine = Color(BrandToken.orangeLine)
    static let successText = Color(BrandToken.successText)
    static let dangerText = Color(BrandToken.dangerText)
}

/// The call: sessions by machine on the left; the conversation, what waits for you, and the talk bar on the right.
struct CallWindow: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        NavigationSplitView {
            SessionSidebar()
                .navigationSplitViewColumnWidth(min: 190, ideal: 230, max: 320)
        } detail: {
            VStack(spacing: 0) {
                Notices()
                stage.frame(maxWidth: .infinity, maxHeight: .infinity)
                    .contentShape(Rectangle())
                    // A click on the conversation takes the keyboard out of the type field, so Space talks again.
                    .simultaneousGesture(TapGesture().onEnded { NSApp.keyWindow?.makeFirstResponder(nil) })
                if let pending = model.store.startPending { StartCard(pending: pending) }
                Approvals()
                Divider()
                TalkBar()
            }
            .background(Brand.card)
        }
        .navigationTitle("Pointe")
        .sheet(isPresented: $model.newSessionShown) { NewSessionSheet().environment(model) }
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                if model.call.state == .live {
                    Button { Task { await model.store.dumpButton() } } label: {
                        Label(BrainDumpCopy.buttonLabel(model.store.dump), systemImage: "brain.head.profile")
                    }
                    .help("Brain dump: talk freely, review, then send (⌘B)")
                    .accessibilityIdentifier("dumpButton")
                }
                Button { Task { await model.toggleCall() } } label: {
                    Label(callLabel, systemImage: model.call.state == .live ? "phone.down.fill" : "phone.fill")
                        .labelStyle(.titleAndIcon)
                }
                .help(model.call.state == .off ? MacCopy.does : MacCopy.hangUp)
                .disabled(model.daemon == .node || model.daemon == .squatter || model.daemon == .noPlugin)
                .accessibilityIdentifier("callButton")
            }
        }
    }

    private var callLabel: String {
        switch model.call.state {
        case .off: MacCopy.connect
        case .connecting, .reconnecting: MacCopy.cancel
        case .live: MacCopy.hangUp
        }
    }

    @ViewBuilder private var stage: some View {
        let store = model.store
        if model.daemon != .running, model.call.state == .off {
            SetupPanel()
        } else if let dump = store.dump {
            BrainDumpPanel(dump: dump)
        } else if model.call.state != .live, (store.status?.talk ?? []).isEmpty {
            ConnectPanel()
        } else {
            Conversation()
        }
    }
}

/// What went wrong last, and a version difference: one quiet line each, above the conversation.
private struct Notices: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(spacing: 0) {
            if let note = model.store.versionNote {
                banner("\(note.line) \(note.fix)", symbol: "arrow.triangle.2.circlepath", id: "versionNote")
            }
            if let notice = model.store.notice {
                banner(notice, symbol: "exclamationmark.triangle", id: "notice")
            }
        }
    }

    private func banner(_ text: String, symbol: String, id: String) -> some View {
        Label(text, systemImage: symbol)
            .font(.callout)
            .foregroundStyle(Brand.accent)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 16).padding(.vertical, 8)
            .background(Brand.tint)
            .textSelection(.enabled)
            .accessibilityIdentifier(id)
    }
}

// MARK: sessions

/// Every session on the voice, grouped by the machine it runs on, this Mac first. Choosing one makes it the session
/// the voice talks to; it sends nothing.
struct SessionSidebar: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let store = model.store
        List(selection: Binding(get: { store.status?.active }, set: { name in
            if let name { Task { await store.switchTo(name) } }
        })) {
            if store.groups.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text(MacCopy.noSessions).font(.headline)
                    Text(MacCopy.noSessionsHow).font(.callout).foregroundStyle(.secondary)
                }
                .padding(.vertical, 6)
                .accessibilityIdentifier("noSessions")
            }
            ForEach(store.groups) { group in
                Section {
                    ForEach(group.sessions) { session in
                        SessionRow(session: session, active: session.name == store.status?.active)
                            .tag(session.name)
                            .contextMenu {
                                Button("Disconnect from the voice") { Task { await store.disconnect(session.name) } }
                            }
                    }
                } header: {
                    Text(group.header).accessibilityIdentifier("machine.\(group.name)")
                }
            }
            if !store.starting.isEmpty {
                Section { ForEach(store.starting) { StartingRow(row: $0).selectionDisabled() } }
            }
        }
        .listStyle(.sidebar)
        .accessibilityIdentifier("sessions")
        .safeAreaInset(edge: .bottom) {
            Button { model.newSessionShown = true } label: { Label(NewSessionCopy.title, systemImage: "plus") }
                .buttonStyle(.borderless)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 14).padding(.vertical, 10)
                .disabled(model.daemon != .running)
                .accessibilityIdentifier("newSession")
        }
    }
}

struct SessionRow: View {
    let session: API.Session
    let active: Bool

    var body: some View {
        let tag = PointeStore.tag(session)
        let hot = session.waiting || session.needs != nil
        HStack(spacing: 8) {
            Text(Harness.mark(session.harness).glyph)
                .font(.system(size: 10, weight: .semibold))
                .frame(width: 16, height: 16)
                .overlay(RoundedRectangle(cornerRadius: 3).stroke(Brand.lineStrong))
                .foregroundStyle(.secondary)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 1) {
                Text(session.name).lineLimit(1)
                if let needs = session.needs, !session.waiting {
                    Text(needs).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                }
            }
            Spacer(minLength: 4)
            Text(tag)
                .font(.caption2.weight(hot ? .semibold : .regular))
                .foregroundStyle(hot ? Brand.accent : .secondary)
                .padding(.horizontal, 6).padding(.vertical, 2)
                .overlay(Capsule().stroke(hot ? Brand.orangeLine : Brand.line))
        }
        .opacity(session.isOffline ? 0.55 : 1)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(session.name), \(tag), runs on \(Harness.mark(session.harness).name)\(active ? ", active" : "")")
        .accessibilityIdentifier("session.\(session.name)")
    }
}

// MARK: the conversation

struct Conversation: View {
    @Environment(AppModel.self) private var model
    @State private var editing: API.Turn?

    var body: some View {
        let store = model.store
        let turns = store.status?.talk ?? []
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 6) {
                    if turns.isEmpty && store.hearing.isEmpty {
                        Text(MacCopy.nothingSaid).foregroundStyle(.secondary).padding(.top, 40)
                    }
                    ForEach(turns) { turn in
                        TurnBubble(turn: turn).onTapGesture { if turn.mine { editing = turn } }
                    }
                    if !store.hearing.isEmpty {
                        HearingBubble(text: store.hearing, draft: store.draftLine)
                    }
                    Color.clear.frame(height: 1).id("end")
                }
                .padding(16)
            }
            .onChange(of: turns.last?.id) { withAnimation { proxy.scrollTo("end", anchor: .bottom) } }
            .onChange(of: store.hearing) { proxy.scrollTo("end", anchor: .bottom) }
            .onAppear { proxy.scrollTo("end", anchor: .bottom) }
        }
        .accessibilityIdentifier("conversation")
        .sheet(item: $editing) { turn in
            EditTurn(turn: turn) { text in await store.correct(turn, to: text) }
        }
    }
}

struct TurnBubble: View {
    let turn: API.Turn

    var body: some View {
        HStack {
            if turn.mine { Spacer(minLength: 60) }
            VStack(alignment: .leading, spacing: 3) {
                Text(turn.understood ?? turn.text).textSelection(.enabled)
                if turn.mine, turn.typed == true || turn.corrected == true {
                    Text([turn.typed == true ? "typed" : nil, turn.corrected == true ? "edited" : nil].compactMap { $0 }.joined(separator: " · "))
                        .font(.caption2).foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 8)
            .background(turn.mine ? Brand.raised : Brand.card, in: RoundedRectangle(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(Brand.line))
            .frame(maxWidth: 520, alignment: turn.mine ? .trailing : .leading)
            if !turn.mine { Spacer(minLength: 60) }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel((turn.mine ? "You: " : "Pointe: ") + (turn.understood ?? turn.text))
        .accessibilityHint(turn.mine ? "Click to fix what was heard" : "")
        .accessibilityIdentifier("turn.\(turn.id)")
    }
}

/// What you are saying right now: live, dashed, and labelled as a draft while a press holds the microphone open.
struct HearingBubble: View {
    let text: String
    let draft: String?

    var body: some View {
        HStack {
            Spacer(minLength: 60)
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: "waveform").foregroundStyle(Brand.accent).accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 2) {
                    if let draft { Text(draft).font(.caption.weight(.semibold)).foregroundStyle(Brand.accent) }
                    Text(text).foregroundStyle(draft == nil ? .primary : .secondary)
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 8)
            .background(Brand.tint, in: RoundedRectangle(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(Brand.orangeLine, style: StrokeStyle(lineWidth: 1, dash: [4, 3])))
            .frame(maxWidth: 520, alignment: .trailing)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(draft.map { "\($0): \(text)" } ?? "Hearing: \(text)")
        .accessibilityIdentifier("hearing")
    }
}

/// Fix what the voice heard. It is told what it heard and what you meant, and fixes anything it did on the wrong words.
struct EditTurn: View {
    let turn: API.Turn
    let send: (String) async -> Bool
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var sending = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Fix it").font(.headline)
            Text("Heard").font(.caption).foregroundStyle(.secondary)
            Text(turn.text).foregroundStyle(.secondary)
            Text("You meant").font(.caption).foregroundStyle(.secondary)
            TextField("What you said", text: $text, axis: .vertical).lineLimit(2...6).accessibilityIdentifier("fixField")
            Text("If it already acted on the misheard words, it says what it did and fixes it.").font(.footnote).foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button(MacCopy.cancel, role: .cancel) { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Send") {
                    sending = true
                    Task {
                        if await send(text) { dismiss() }
                        sending = false
                    }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(sending || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || text == turn.text)
            }
        }
        .padding(20)
        .frame(width: 420)
        .onAppear { text = turn.text }
    }
}

// MARK: approvals

/// Each request that waits for a click: the exact request, Deny, and Approve, which asks for Touch ID or the password.
struct Approvals: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let pending = model.store.pending
        if !pending.isEmpty {
            VStack(spacing: 8) {
                ForEach(pending) { approval in ApprovalCard(approval: approval) }
            }
            .padding(.horizontal, 16).padding(.vertical, 10)
            .background(Brand.tint)
            .accessibilityIdentifier("approvals")
        }
    }
}

struct ApprovalCard: View {
    @Environment(AppModel.self) private var model
    let approval: PendingApproval

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text("\(approval.label) wants to run").font(.callout.weight(.semibold))
                Text(approval.request)
                    .font(.system(.callout, design: .monospaced))
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("request.\(approval.session.name)")
                if approval.offline { Text(MacCopy.offlineCard).font(.caption).foregroundStyle(.secondary) }
            }
            Spacer(minLength: 8)
            if !approval.offline {
                Button(MacCopy.deny) { Task { await model.store.deny(approval) } }
                    .accessibilityIdentifier("deny.\(approval.session.name)")
                    .accessibilityHint("Denies this request. No authentication needed.")
                Button(MacCopy.approve) { Task { await model.store.approve(approval) } }
                    .buttonStyle(.borderedProminent)
                    .accessibilityIdentifier("approve.\(approval.session.name)")
                    .accessibilityHint("Approves exactly this request, after Touch ID or your password.")
            }
        }
        .padding(12)
        .background(Brand.card, in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Brand.orangeLine))
        .disabled(model.store.busy)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("\(approval.label) needs approval")
    }
}

// MARK: connect, and the talk bar

/// No call up and nothing said yet: one button, and the reason in plain words when the last attempt failed.
struct ConnectPanel: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let why = model.store.connectWhy
        let dialling = model.call.state == .connecting || model.call.state == .reconnecting
        VStack(spacing: 12) {
            Image(systemName: "phone.fill").font(.system(size: 26, weight: .semibold)).foregroundStyle(.secondary)
                .frame(width: 68, height: 68).background(Brand.raised, in: Circle()).accessibilityHidden(true)
            Text(model.store.stateTitle).font(.title2).accessibilityIdentifier("connectTitle")
            Text(why.line).font(.callout).foregroundStyle(why.bad ? Brand.accent : .secondary)
                .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("connectWhy")
            Button { Task { await model.toggleCall() } } label: {
                HStack(spacing: 8) {
                    if dialling { ProgressView().controlSize(.small) } else { Image(systemName: "phone.fill") }
                    Text(dialling ? MacCopy.cancel : why.bad ? MacCopy.tryAgain : MacCopy.connect).fontWeight(.semibold)
                }
                .padding(.horizontal, 18).frame(height: 40)
                .foregroundStyle(dialling ? Color.primary : Brand.onOrange)
                .background(dialling ? Brand.raised : Brand.orange, in: RoundedRectangle(cornerRadius: 10))
            }
            .buttonStyle(.plain)
            .keyboardShortcut(.defaultAction)
            .accessibilityIdentifier("connectButton")
            if model.micDenied {
                Button("Open Microphone settings…") { model.openMicrophoneSettings() }.buttonStyle(.link)
            }
            Text(MacCopy.typeLater).font(.caption).foregroundStyle(.tertiary)
        }
        .padding(28)
        .frame(maxWidth: 400)
    }
}

/// The state, the talk control (hold or tap in push to talk, mute in Always on), and a field to type instead.
struct TalkBar: View {
    @Environment(AppModel.self) private var model
    @State private var text = ""
    @State private var pressed = false
    @FocusState private var typing: Bool

    var body: some View {
        let call = model.call, live = call.state == .live
        HStack(spacing: 12) {
            talkControl(live: live)
            VStack(alignment: .leading, spacing: 1) {
                // The value is what the last press did ("held 412 ms"): the UI tests read it.
                Text(model.store.stateTitle).font(.callout.weight(.medium)).lineLimit(1)
                    .accessibilityIdentifier("state").accessibilityValue(call.talkTrace)
                if live, let rtt = call.rttMs { Text("\(rtt) ms").font(.caption2).foregroundStyle(.tertiary) }
            }
            .frame(minWidth: 130, alignment: .leading)
            TextField(MacCopy.typeHere, text: $text)
                .textFieldStyle(.roundedBorder)
                .focused($typing)
                .onSubmit(send)
                .disabled(!live)
                .accessibilityIdentifier("typeField")
                .help("Typed words are sent like speech. They never approve a request.")
            Button("Send", action: send)
                .disabled(!live || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .accessibilityIdentifier("sendButton")
        }
        .padding(.horizontal, 16).padding(.vertical, 10)
        .background(.bar)
        // The call came up: the keyboard is the talk key's until the person clicks the field.
        .onChange(of: live) { if live { typing = false; NSApp.keyWindow?.makeFirstResponder(nil) } }
        // Space, when no field has the keyboard: the talk key in push to talk, mute in Always on (the page's rule).
        .background(SpaceKey(enabled: live && !typing, down: { spaceDown() }, up: { call.talkUp(.key) }))
    }

    @ViewBuilder private func talkControl(live: Bool) -> some View {
        let call = model.call
        let ptt = call.talk.ptt
        let open = call.talk.shows(macOpen: model.store.status?.ptt?.open == true && ptt)
        let symbol = !live ? "mic.slash" : ptt ? (open ? "mic.fill" : "mic") : (call.muted ? "mic.slash.fill" : "mic.fill")
        Image(systemName: symbol)
            .font(.system(size: 17, weight: .semibold))
            .frame(width: 40, height: 40)
            .foregroundStyle(open ? Brand.onOrange : live ? Color.primary : Color.secondary)
            .background(open ? Brand.orange : Brand.raised, in: Circle())
            .overlay(Circle().stroke(open ? Color.clear : Brand.lineStrong))
            .contentShape(Circle())
            .gesture(DragGesture(minimumDistance: 0)
                .onChanged { _ in
                    guard live, !pressed else { return }
                    pressed = true
                    if ptt { call.talkDown(.ring) } else { call.toggleMute() }
                }
                .onEnded { _ in
                    pressed = false
                    if ptt { call.talkUp(.ring) }
                })
            .accessibilityElement()
            .accessibilityAddTraits(.isButton)
            .accessibilityLabel(!live ? MacCopy.notConnected : ptt ? (open ? "Talking" : call.talkStyle.label) : (call.muted ? "Unmute" : "Mute"))
            .accessibilityHint(ptt ? call.talkStyle.hint : "")
            .accessibilityAction { if live { if ptt { call.talkToggle() } else { call.toggleMute() } } }
            .accessibilityIdentifier("talkButton")
            .help(ptt ? call.talkStyle.label : "Mute (Space)")
    }

    private func spaceDown() {
        let call = model.call
        if call.talk.ptt { call.talkDown(.key) } else { call.toggleMute() }
    }

    private func send() {
        let words = text
        text = ""
        Task { if !(await model.store.say(words)) { text = words } }
    }
}

/// Space, down and up, while the window is key and no text field is editing: a local monitor sees only this app's keys.
private struct SpaceKey: NSViewRepresentable {
    let enabled: Bool
    let down: () -> Void
    let up: () -> Void

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        context.coordinator.install(for: view)
        return view
    }

    func updateNSView(_ view: NSView, context: Context) {
        context.coordinator.enabled = enabled
        context.coordinator.down = down
        context.coordinator.up = up
    }

    static func dismantleNSView(_ view: NSView, coordinator: Coordinator) { coordinator.remove() }
    func makeCoordinator() -> Coordinator { Coordinator() }

    @MainActor final class Coordinator {
        var enabled = false
        var down: () -> Void = {}
        var up: () -> Void = {}
        private var monitor: Any?
        private var held = false
        private weak var view: NSView?

        func install(for view: NSView) {
            self.view = view
            monitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .keyUp]) { [weak self] event in
                let plain = event.modifierFlags.intersection([.command, .option, .control]).isEmpty
                guard event.keyCode == 49, plain else { return event }
                let (up, again, number) = (event.type == .keyUp, event.isARepeat, event.windowNumber)
                let taken = MainActor.assumeIsolated { self?.handle(up: up, repeated: again, windowNumber: number) ?? false }
                return taken ? nil : event
            }
        }

        func remove() {
            if let monitor { NSEvent.removeMonitor(monitor) }
            monitor = nil
        }

        /// True when the Space was the talk key's, and so is not passed on.
        private func handle(up isUp: Bool, repeated: Bool, windowNumber: Int) -> Bool {
            guard let window = view?.window, window.windowNumber == windowNumber else { return false }
            if isUp {
                guard held else { return false }
                held = false
                up()
                return true
            }
            // A field being typed in, or a button that Space would press, keeps its Space. Text that is only selectable
            // (a bubble, a request) does not.
            let responder = window.firstResponder
            let typing = (responder as? NSTextView)?.isEditable == true
            guard enabled, !typing, !(responder is NSControl) else { return false }
            if !repeated, !held {
                held = true
                down()
            }
            return true
        }
    }
}
