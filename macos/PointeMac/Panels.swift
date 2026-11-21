import AVFoundation
import PointeKit
import PointeMacKit
import SwiftUI

// MARK: brain dump (docs/design/brain-dump.md)

/// You dump your thoughts and Pointe stays quiet; then it shows them structured, in your words, for review. Only an
/// explicit Send puts it in a session, on the second click. The daemon holds the state and the rules.
struct BrainDumpPanel: View {
    @Environment(AppModel.self) private var model
    let dump: API.BrainDump
    @State private var draft = ""
    @State private var draftFor = ""
    @State private var discardSure = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if dump.inReview { review } else { dumping }
            }
            .padding(20)
            .frame(maxWidth: 640, alignment: .leading)
        }
        .frame(maxWidth: .infinity)
        .accessibilityIdentifier("dump")
    }

    @ViewBuilder private var dumping: some View {
        Label(BrainDumpCopy.title, systemImage: "brain.head.profile").font(.title2).accessibilityAddTraits(.isHeader)
        Text(BrainDumpCopy.lede).foregroundStyle(.secondary)
        if dump.resumed == true { Text(BrainDumpCopy.resumed).font(.callout).foregroundStyle(Brand.accent) }
        if dump.state == "structuring" {
            HStack(spacing: 8) { ProgressView().controlSize(.small); Text(BrainDumpCopy.structuring) }
        } else if dump.thoughts.isEmpty && model.store.hearing.isEmpty {
            Text(BrainDumpCopy.empty).foregroundStyle(.tertiary)
        }
        ForEach(Array(dump.thoughts.enumerated()), id: \.offset) { _, thought in
            Text(thought.text).padding(10).frame(maxWidth: .infinity, alignment: .leading)
                .background(Brand.raised, in: RoundedRectangle(cornerRadius: 8))
        }
        if !model.store.hearing.isEmpty { HearingBubble(text: model.store.hearing, draft: model.store.draftLine) }
        if let problem = dump.problem { Text(problem).foregroundStyle(Brand.accent) }
        Text(BrainDumpCopy.hint).font(.footnote).foregroundStyle(.secondary)
        HStack {
            discard
            Spacer()
            Button(BrainDumpCopy.done) { Task { await model.store.dumpAction("done") } }
                .buttonStyle(.borderedProminent)
                .disabled(dump.state == "structuring" || model.store.busy)
                .accessibilityIdentifier("dump.done")
        }
    }

    @ViewBuilder private var review: some View {
        let store = model.store
        Text(BrainDumpCopy.reviewTitle).font(.title2).accessibilityAddTraits(.isHeader)
        Text(BrainDumpCopy.reviewLede).foregroundStyle(.secondary)
        if dump.fallback == true { Text(BrainDumpCopy.fallback).font(.callout).foregroundStyle(Brand.accent) }
        TextEditor(text: $draft)
            .font(.body)
            .frame(minHeight: 150)
            .padding(6)
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Brand.lineStrong))
            .accessibilityLabel(BrainDumpCopy.reviewTitle)
            .accessibilityIdentifier("dump.text")
            .onAppear(perform: loadDraft)
            .onChange(of: dump.prompt?.text) { loadDraft() }
        if let problem = dump.problem { Text(problem).foregroundStyle(Brand.accent) }
        HStack {
            Text(BrainDumpCopy.to)
            Picker(BrainDumpCopy.sendTo, selection: Binding(get: { store.dumpTarget ?? .orchestrator }, set: { picked in
                store.dumpPicked = picked
                store.disarmDumpSend()
            })) {
                ForEach(store.dumpChoices, id: \.self) { Text($0.label).tag($0) }
            }
            .labelsHidden()
            .frame(maxWidth: 240)
            .accessibilityIdentifier("dump.to")
        }
        if let gone = BrainDumpCopy.goneNote(dump, target: store.dumpTarget) { Text(gone).font(.footnote).foregroundStyle(.secondary) }
        Text(BrainDumpCopy.reviewHint).font(.footnote).foregroundStyle(.secondary)
        HStack {
            discard
            Button(BrainDumpCopy.addMore) { Task { await saveEdit(); await store.dumpAction("more") } }.accessibilityIdentifier("dump.more")
            Button(BrainDumpCopy.readBack) { Task { await saveEdit(); await store.dumpAction("read") } }
            Spacer()
            Button(store.dumpSendArmed ? BrainDumpCopy.sendSure : "\(BrainDumpCopy.sendTo) \(store.dumpTarget?.label ?? "")") {
                Task {
                    await saveEdit()
                    await store.dumpSend()
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(store.busy || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            .accessibilityIdentifier("dump.send")
        }
    }

    private var discard: some View {
        Button(discardSure ? BrainDumpCopy.discardSure : BrainDumpCopy.discard, role: .destructive) {
            if discardSure { Task { await model.store.dumpAction("discard") } } else { discardSure = true }
        }
        .accessibilityIdentifier("dump.discard")
    }

    /// The daemon's text, unless the person is editing this same prompt.
    private func loadDraft() {
        let text = dump.prompt?.text ?? ""
        if draftFor != dump.id || draft.isEmpty { draft = text }
        draftFor = dump.id
    }

    /// An edit goes to the daemon before anything is done with the prompt: what is sent is what the screen shows.
    private func saveEdit() async {
        guard draft != dump.prompt?.text, !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        let armed = model.store.dumpSendArmed
        await model.store.dumpAction("edit", text: draft)
        if armed { await model.store.dumpSend() }  // the edit must not cost the first click
    }
}

// MARK: setup

/// Pointe on this Mac is not ready: each step with its state, and the one thing to do about it.
struct SetupPanel: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Set up Pointe").font(.title2).accessibilityAddTraits(.isHeader)
            step(done: model.plugin != nil, title: "The Pointe plugin",
                 detail: model.plugin.map { "Found version \($0.version)." } ?? "Install it in a terminal, then come back:") {
                if model.plugin == nil {
                    HStack {
                        Text(MacCopy.installCommand).font(.system(.caption, design: .monospaced)).textSelection(.enabled).lineLimit(2)
                        Button("Copy") {
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(MacCopy.installCommand, forType: .string)
                        }
                    }
                }
            }
            step(done: model.keys.values.contains(true), title: "A model key, in your Keychain",
                 detail: model.keys.values.contains(true) ? "Found. The app never reads it; Pointe on this Mac does."
                    : "One key is enough to start (or run pointe local for none).") {
                Button("Keys…") { model.windows.activate(); openSettings() }
            }
            step(done: model.daemon == .running, title: "Pointe on this Mac", detail: model.daemonLine) {
                switch model.daemon {
                case .stopped, .failed:
                    Button("Start Pointe") { Task { await model.startDaemon() } }.buttonStyle(.borderedProminent).accessibilityIdentifier("startDaemon")
                case .starting, .checking: ProgressView().controlSize(.small)
                default: EmptyView()
                }
            }
            step(done: AVCaptureDevice.authorizationStatus(for: .audio) == .authorized, title: "The microphone",
                 detail: AVCaptureDevice.authorizationStatus(for: .audio) == .denied ? MacCopy.micDenied : "macOS asks the first time you press Connect.") {
                if AVCaptureDevice.authorizationStatus(for: .audio) == .denied {
                    Button("Open Microphone settings…") { model.openMicrophoneSettings() }
                }
            }
            step(done: !(model.store.status?.sessions ?? []).isEmpty, title: "A session", detail: MacCopy.noSessionsHow) { EmptyView() }
        }
        .padding(28)
        .frame(maxWidth: 520, alignment: .leading)
        .onAppear { model.refreshKeys() }
        .accessibilityIdentifier("setup")
    }

    private func step<Action: View>(done: Bool, title: String, detail: String, @ViewBuilder action: () -> Action) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: done ? "checkmark.circle.fill" : "circle")
                .foregroundStyle(done ? Brand.successText : .secondary)
                .accessibilityLabel(done ? "Done" : "To do")
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.headline)
                Text(detail).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                action()
            }
        }
        .accessibilityElement(children: .contain)
    }
}

// MARK: the call bubble

/// The call in a corner of the screen: the state, what is being heard, a talk button and who waits. It floats over
/// other apps and never takes the keyboard from them.
struct BubbleView: View {
    @Environment(AppModel.self) private var model
    @State private var pressed = false

    var body: some View {
        let store = model.store, call = model.call
        let live = call.state == .live, ptt = call.talk.ptt
        let open = call.talk.isOpen
        HStack(spacing: 10) {
            Image(systemName: !live ? "phone.fill" : ptt ? (open ? "mic.fill" : "mic") : (call.muted ? "mic.slash.fill" : "mic.fill"))
                .font(.system(size: 15, weight: .semibold))
                .frame(width: 36, height: 36)
                .foregroundStyle(open ? Brand.onOrange : Color.primary)
                .background(open ? Brand.orange : Brand.raised, in: Circle())
                .contentShape(Circle())
                .gesture(DragGesture(minimumDistance: 0)
                    .onChanged { _ in
                        guard !pressed else { return }
                        pressed = true
                        if !live { Task { await model.toggleCall() } } else if ptt { call.talkDown(.caption) } else { call.toggleMute() }
                    }
                    .onEnded { _ in
                        pressed = false
                        if live, ptt { call.talkUp(.caption) }
                    })
                .accessibilityElement()
                .accessibilityAddTraits(.isButton)
                .accessibilityLabel(!live ? MacCopy.connect : ptt ? (open ? "Talking" : call.talkStyle.label) : (call.muted ? "Unmute" : "Mute"))
                .accessibilityAction { if !live { Task { await model.toggleCall() } } else if ptt { call.talkToggle() } else { call.toggleMute() } }
                .accessibilityIdentifier("bubble.talk")
            VStack(alignment: .leading, spacing: 1) {
                Text(store.stateTitle).font(.callout.weight(.medium)).lineLimit(1).accessibilityIdentifier("bubble.state")
                Text(store.hearing.isEmpty ? (store.status?.active ?? MacCopy.appName) : store.hearing)
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.head)
            }
            Spacer(minLength: 0)
            if store.needCount > 0 {
                Button { model.windows.showMain() } label: {
                    Text("\(store.needCount)").font(.caption.weight(.bold)).monospacedDigit()
                        .frame(minWidth: 20, minHeight: 20).foregroundStyle(Brand.onOrange).background(Brand.orange, in: Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(MacCopy.needYou(store.needCount))
                .help(MacCopy.needYou(store.needCount))
            }
        }
        .padding(.horizontal, 12)
        .frame(width: 260, height: 60)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 18))
        .overlay(RoundedRectangle(cornerRadius: 18).stroke(Brand.lineStrong))
        .padding(2)
        .contextMenu {
            Button("Open Pointe") { model.windows.showMain() }
            Button("Hide the bubble") { model.bubbleOn = false }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Pointe call bubble")
    }
}
