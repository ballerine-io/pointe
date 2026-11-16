import SwiftUI

// Brain dump (docs/design/brain-dump.md): you dump your thoughts, Pointe stays quiet and keeps every word, then structures
// them into a prompt in your own words for review; only an explicit send puts it in a session. The Mac holds the state and
// the rules (braindump.py); the phone starts it, shows the thoughts, then the prompt, and sends on your tap.

extension API {
    struct Thought: Decodable, Equatable, Hashable {
        let text: String
        let at: Double?
    }

    /// The structured prompt: the sections, and the text that is shown and sent (the text wins once edited).
    struct DumpPrompt: Decodable, Equatable {
        var goal: String?
        var context: [String]?
        var constraints: [String]?
        var open_questions: [String]?
        var text: String
    }

    /// Where Send goes unless the user picks another (braindump.send_to): the routing when the dump started. `gone`: the
    /// pinned session that left, so the default fell back to the orchestrator.
    struct DumpSendTo: Decodable, Equatable {
        var orchestrator: Bool
        var session: String?
        var gone: String?
    }

    /// Dumping, structuring, or in review; nil when there is none.
    struct BrainDump: Decodable, Equatable {
        var id: String
        var state: String            // dumping | structuring | review
        let since: Double?
        var thoughts: [Thought]
        var dropped: Int?
        var prompt: DumpPrompt?
        var target: String?          // the session named by voice for the send
        var problem: String?         // why the last action was refused
        var resumed: Bool?           // left from a dropped call or the last run
        var fallback: Bool?          // the model could not structure it: the prompt is the thoughts as said
        var send_to: DumpSendTo?     // nil from a Mac before 1.7, which cannot send to the orchestrator

        var isDumping: Bool { state != "review" }
        var inReview: Bool { state == "review" && prompt != nil }
    }
}

extension API.Status {
    var dumping: Bool { brain_dump?.isDumping == true }
}

/// Word for word the page's copy (ui.html DUMP_COPY) and the daemon's (braindump.COPY): the three must not drift
/// (tests/test_brain_dump.py).
enum BrainDumpCopy {
    static let button = "Brain dump"
    static let done = "Done"
    static let title = "Brain dump"
    static let lede = "Talk freely. Nothing is sent until you say so."
    static let empty = "Start talking. Every thought lands here."
    static let hint = "When you're done: tap Done, or say “done” or “over to you”."
    static let structuring = "Structuring your thoughts…"
    static let reviewTitle = "Your brain dump, structured"
    static let reviewLede = "In your words. Edit it, add more, or send it."
    static let reviewHint = "Or say “send it to …”, “add more”, “read it back” or “discard”."
    static let addMore = "Add more"
    static let discard = "Discard"
    static let discardSure = "Discard the dump?"
    static let to = "To:"
    static let send = "Send"
    static let sendSure = "Tap again to send"
    static let sendTo = "Send to"
    static let sent = "Sent to"
    static let orchestrator = "Orchestrator"
    static let gone = "is gone, so this goes to the orchestrator."
    static let readBack = "Read it back"
    static let fallback = "Pointe could not structure it; this is what you said."
    static let resumed = "Still here from earlier."
    static let state = "Brain dump"
    static let review = "Review"

    /// The dock button's word: start, done, or open the review.
    static func buttonLabel(_ dump: API.BrainDump?) -> String {
        guard let dump else { return button }
        return dump.isDumping ? done : review
    }

    /// Where the send goes: the one picked here, else where the Mac says (the routing when the dump started). A Mac
    /// before 1.7 sends no `send_to` and cannot take the orchestrator: there, the session named by voice, else the active one.
    static func target(_ dump: API.BrainDump, picked: DumpTarget?, active: String?, sessions: [String]) -> DumpTarget? {
        let offered = choices(dump, sessions: sessions)
        if let picked, offered.contains(picked) { return picked }
        guard let to = dump.send_to else {
            return ([dump.target, active].compactMap { $0 }.first { sessions.contains($0) } ?? sessions.first).map { .session($0) }
        }
        if !to.orchestrator, let name = to.session, sessions.contains(name) { return .session(name) }
        return .orchestrator
    }

    /// The To: menu, the orchestrator first, as on the page; only the sessions for a Mac that cannot take the orchestrator.
    static func choices(_ dump: API.BrainDump, sessions: [String]) -> [DumpTarget] {
        (dump.send_to == nil ? [] : [.orchestrator]) + sessions.map { .session($0) }
    }

    /// The pinned session that left, when the send falls back to the orchestrator because of it: said under To:.
    static func goneNote(_ dump: API.BrainDump, target: DumpTarget?) -> String? {
        guard target == .orchestrator, let name = dump.send_to?.gone else { return nil }
        return "\(name) \(gone)"
    }
}

/// Where a reviewed dump goes: Pointe's orchestrator voice (it answers or routes it), or one session, word for word.
enum DumpTarget: Hashable {
    case orchestrator
    case session(String)

    var label: String {
        switch self {
        case .orchestrator: BrainDumpCopy.orchestrator
        case .session(let name): name
        }
    }
}

/// Dumping: the thoughts as they land, the live hearing line, Done and Discard.
struct BrainDumpPanel: View {
    let dump: API.BrainDump
    let hearing: String
    let done: () -> Void
    let discard: () -> Void
    var problem: String? = nil
    @State private var discardSure = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 10) {  // the state line above already says "Brain dump": the title is the heading VoiceOver reads
                Image(systemName: "brain.head.profile").font(.brand(.title2)).foregroundStyle(Brand.accent)
                    .symbolEffect(.pulse, options: .repeating)
                    .accessibilityLabel(BrainDumpCopy.title).accessibilityAddTraits(.isHeader).accessibilityIdentifier("dump.title")
                Text(BrainDumpCopy.lede).foregroundStyle(Brand.muted)
            }
            ScrollViewReader { scroller in
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        if dump.thoughts.isEmpty && hearing.isEmpty {
                            Text(BrainDumpCopy.empty).foregroundStyle(Brand.muted)
                        }
                        ForEach(Array(dump.thoughts.enumerated()), id: \.offset) { _, thought in
                            Text(thought.text).readingDirection(of: thought.text).font(.brand(.body))
                                .padding(.horizontal, 12).padding(.vertical, 8)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(Brand.raised, in: RoundedRectangle(cornerRadius: 12))
                                .accessibilityIdentifier("dump.thought")
                        }
                        if dump.state == "structuring" {
                            Label(BrainDumpCopy.structuring, systemImage: "sparkles").foregroundStyle(Brand.muted)
                                .accessibilityIdentifier("dump.structuring")
                        } else if !hearing.isEmpty {
                            Text(hearing).readingDirection(of: hearing).font(.brand(.body)).foregroundStyle(Brand.muted)
                        }
                        Color.clear.frame(height: 1).id("end")
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .animation(.easeOut(duration: 0.15), value: dump.thoughts.count)
                }
                .defaultScrollAnchor(.bottom)
                .onChange(of: dump.thoughts.count) { scroller.scrollTo("end", anchor: .bottom) }
            }
            Text(BrainDumpCopy.hint).font(.brand(.footnote)).foregroundStyle(Brand.muted)
            if let note = problem ?? dump.problem ?? (dump.resumed == true ? BrainDumpCopy.resumed : nil) {
                Label(note, systemImage: "exclamationmark.triangle.fill").font(.brand(.footnote)).foregroundStyle(Brand.accent)
                    .accessibilityIdentifier("dump.note")
            }
            HStack(spacing: 10) {
                Button {
                    if discardSure { discardSure = false; discard() } else {
                        discardSure = true
                        Task { try? await Task.sleep(for: .seconds(4)); discardSure = false }
                    }
                } label: {
                    Text(discardSure ? BrainDumpCopy.discardSure : BrainDumpCopy.discard).font(.brand(.headline)).padding(.vertical, 6)
                }
                .buttonStyle(.brandQuiet).controlSize(.large)
                .accessibilityIdentifier("dump.discard")
                Button(action: done) {
                    Label(dump.state == "structuring" ? BrainDumpCopy.structuring : BrainDumpCopy.done, systemImage: "checkmark")
                        .font(.brand(.headline)).lineLimit(1).minimumScaleFactor(0.8).frame(maxWidth: .infinity).padding(.vertical, 6)
                }
                .buttonStyle(.brandPrimary).controlSize(.large)
                .disabled(dump.state == "structuring")
                .accessibilityIdentifier("dump.done")
            }
        }
        .padding(20)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .dynamicTypeSize(...DynamicTypeSize.accessibility1)  // past this the hint and the two buttons are cut to fit
        .background(Brand.card, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.orangeLine))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("dump.panel")
    }
}

/// Review: the structured prompt, editable, where it goes, and Send / Add more / Read it back / Challenge / Discard.
struct BrainDumpReview: View {
    let dump: API.BrainDump
    let sessions: [String]
    let active: String?
    let problem: String?
    let edit: (String) async -> Bool
    let send: (DumpTarget) async -> Bool
    let more: () async -> Void
    let read: () async -> Void
    let challenge: () async -> Void
    let discard: () async -> Void
    let close: () -> Void
    @State private var text = ""
    @State private var picked: DumpTarget?
    @State private var sure = false
    @State private var discardSure = false
    @State private var busy = false
    @FocusState private var editing: Bool

    private var target: DumpTarget? { BrainDumpCopy.target(dump, picked: picked, active: active, sessions: sessions) }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text(BrainDumpCopy.reviewLede).font(.brand(.subheadline)).foregroundStyle(Brand.muted)
                    if dump.fallback == true {
                        Label(BrainDumpCopy.fallback, systemImage: "exclamationmark.triangle.fill").font(.brand(.footnote)).foregroundStyle(Brand.accent)
                            .accessibilityIdentifier("dump.fallback")
                    }
                    TextEditor(text: $text)
                        .font(.brand(.body))
                        .frame(minHeight: 220)
                        .scrollContentBackground(.hidden)
                        .padding(10)
                        .background(Brand.card, in: RoundedRectangle(cornerRadius: 12))
                        .focused($editing)
                        .onChange(of: editing) { if !editing { Task { await saveEdit() } } }
                        .accessibilityIdentifier("dump.text")
                    // To: a field, like Mail's, so it never reads as a second button; Send is the one primary action.
                    Menu {
                        Picker("Send to", selection: Binding(get: { target ?? .orchestrator }, set: { picked = $0; sure = false })) {
                            ForEach(BrainDumpCopy.choices(dump, sessions: sessions), id: \.self) { Text($0.label).tag($0) }
                        }
                    } label: {
                        HStack(spacing: 8) {
                            Text(BrainDumpCopy.to).foregroundStyle(Brand.muted)
                            Text(target?.label ?? "").fontWeight(.semibold).foregroundStyle(.primary).lineLimit(1)
                            Spacer(minLength: 0)
                            Image(systemName: "chevron.up.chevron.down").font(.brand(.footnote, .semibold)).foregroundStyle(Brand.muted)
                        }
                        .padding(.horizontal, 14).frame(minHeight: 46)
                        .background(Brand.card, in: RoundedRectangle(cornerRadius: 12))
                        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Brand.line))
                    }
                    .tint(.primary)  // a field, not an accent: the orange is Send's
                    .accessibilityLabel("\(BrainDumpCopy.to) \(target?.label ?? "")")
                    .accessibilityIdentifier("dump.session")
                    if let note = BrainDumpCopy.goneNote(dump, target: target) {
                        Label(note, systemImage: "arrow.uturn.left").font(.brand(.footnote)).foregroundStyle(Brand.accent)
                            .accessibilityIdentifier("dump.gone")
                    }
                    if let note = problem ?? dump.problem {
                        Label(note, systemImage: "exclamationmark.triangle.fill").font(.brand(.footnote)).foregroundStyle(Brand.accent)
                            .accessibilityIdentifier("dump.problem")
                    }
                    Button {
                        guard let target else { return }
                        if !sure { sure = true; Task { try? await Task.sleep(for: .seconds(4)); sure = false }; return }
                        sure = false; busy = true
                        Task {
                            _ = await saveEdit()
                            _ = await send(target)  // the Mac clears the dump: the sheet goes with it, and Pointe says it went
                            busy = false
                        }
                    } label: {
                        Text(sure ? BrainDumpCopy.sendSure : BrainDumpCopy.send)
                            .font(.brand(.headline)).frame(maxWidth: .infinity).padding(.vertical, 6)
                    }
                    .buttonStyle(.brandPrimary).controlSize(.large)
                    .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.orange, lineWidth: 2).padding(-4).opacity(sure ? 1 : 0))
                    .animation(.easeOut(duration: 0.15), value: sure)
                    .disabled(target == nil || busy)
                    .accessibilityLabel(sure ? BrainDumpCopy.sendSure : "\(BrainDumpCopy.sendTo) \(target?.label ?? "")")
                    .accessibilityIdentifier("dump.send")
                    HStack(spacing: 8) {
                        quiet(BrainDumpCopy.addMore, id: "dump.more") { await more() }
                        quiet(BrainDumpCopy.readBack, id: "dump.read") { await read() }
                        quiet(ChallengeCopy.fromDump, id: "dump.challenge") { await challenge() }
                    }
                    Button(role: .destructive) {
                        if discardSure { discardSure = false; Task { await discard() } } else {
                            discardSure = true
                            Task { try? await Task.sleep(for: .seconds(4)); discardSure = false }
                        }
                    } label: {
                        Text(discardSure ? BrainDumpCopy.discardSure : BrainDumpCopy.discard).font(.brand(.subheadline, .semibold))
                            .padding(.horizontal, 16).padding(.vertical, 8)
                    }
                    .buttonStyle(.plain).foregroundStyle(Brand.dangerText)
                    .frame(maxWidth: .infinity).padding(.top, 6)
                    .accessibilityIdentifier("dump.discard")
                    Text(BrainDumpCopy.reviewHint).font(.brand(.footnote)).foregroundStyle(Brand.muted)
                        .multilineTextAlignment(.center).frame(maxWidth: .infinity)
                }
                .padding(20)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("dump.review")
            }
            .navigationTitle(BrainDumpCopy.reviewTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close", action: close).accessibilityIdentifier("dump.close") } }
        }
        .onAppear { text = dump.prompt?.text ?? "" }
        .onChange(of: dump.prompt?.text) { if !editing, let t = dump.prompt?.text { text = t } }
    }

    /// A secondary action: quiet, outlined, never competing with Send.
    private func quiet(_ title: String, id: String, _ action: @escaping () async -> Void) -> some View {
        Button { Task { await action() } } label: {
            Text(title).font(.brand(.subheadline)).lineLimit(1).minimumScaleFactor(0.8).frame(maxWidth: .infinity).frame(minHeight: 40)
                .overlay(Capsule().stroke(Brand.line))
                .contentShape(Capsule())
        }
        .buttonStyle(.plain).foregroundStyle(.primary)
        .accessibilityIdentifier(id)
    }

    private func saveEdit() async -> Bool {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, t != dump.prompt?.text else { return true }
        return await edit(t)
    }
}
