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
    static let reviewLede = "In your words. Edit it, add more, or send it to a session."
    static let reviewHint = "Or say “send it to …”, “add more”, “read it back” or “discard”."
    static let addMore = "Add more"
    static let discard = "Discard"
    static let discardSure = "Discard the dump?"
    static let to = "To:"
    static let send = "Send"
    static let sendSure = "Tap again to send"
    static let sendTo = "Send to"
    static let sent = "Sent to"
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

    /// Which session the send goes to: the one named by voice, else the one picked here, else the active one.
    static func target(_ dump: API.BrainDump, picked: String?, active: String?, sessions: [String]) -> String? {
        [dump.target, picked, active].compactMap { $0 }.first { sessions.contains($0) } ?? sessions.first
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
            HStack(spacing: 10) {
                Image(systemName: "brain.head.profile").font(.title2).foregroundStyle(Brand.orange)
                    .symbolEffect(.pulse, options: .repeating)
                VStack(alignment: .leading, spacing: 2) {
                    Text(BrainDumpCopy.title).font(.title2.bold()).accessibilityIdentifier("dump.title")
                    Text(BrainDumpCopy.lede).foregroundStyle(.secondary)
                }
            }
            ScrollViewReader { scroller in
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        if dump.thoughts.isEmpty && hearing.isEmpty {
                            Text(BrainDumpCopy.empty).foregroundStyle(.secondary)
                        }
                        ForEach(Array(dump.thoughts.enumerated()), id: \.offset) { _, thought in
                            Text(thought.text).readingDirection(of: thought.text).font(.body)
                                .padding(.horizontal, 12).padding(.vertical, 8)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(Brand.card, in: RoundedRectangle(cornerRadius: 12))
                                .accessibilityIdentifier("dump.thought")
                        }
                        if dump.state == "structuring" {
                            Label(BrainDumpCopy.structuring, systemImage: "sparkles").foregroundStyle(.secondary)
                                .accessibilityIdentifier("dump.structuring")
                        } else if !hearing.isEmpty {
                            Text(hearing).readingDirection(of: hearing).font(.body).italic().foregroundStyle(.white.opacity(0.6))
                        }
                        Color.clear.frame(height: 1).id("end")
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .animation(.easeOut(duration: 0.15), value: dump.thoughts.count)
                }
                .defaultScrollAnchor(.bottom)
                .onChange(of: dump.thoughts.count) { scroller.scrollTo("end", anchor: .bottom) }
            }
            Text(BrainDumpCopy.hint).font(.footnote).foregroundStyle(.secondary)
            if let note = problem ?? dump.problem ?? (dump.resumed == true ? BrainDumpCopy.resumed : nil) {
                Label(note, systemImage: "exclamationmark.triangle.fill").font(.footnote).foregroundStyle(Brand.orange)
                    .accessibilityIdentifier("dump.note")
            }
            HStack(spacing: 10) {
                Button {
                    if discardSure { discardSure = false; discard() } else {
                        discardSure = true
                        Task { try? await Task.sleep(for: .seconds(4)); discardSure = false }
                    }
                } label: {
                    Text(discardSure ? BrainDumpCopy.discardSure : BrainDumpCopy.discard).font(.headline).padding(.vertical, 6)
                }
                .buttonStyle(.bordered).tint(.gray).controlSize(.large)
                .accessibilityIdentifier("dump.discard")
                Button(action: done) {
                    Label(dump.state == "structuring" ? BrainDumpCopy.structuring : BrainDumpCopy.done, systemImage: "checkmark")
                        .font(.headline).lineLimit(1).minimumScaleFactor(0.8).frame(maxWidth: .infinity).padding(.vertical, 6)
                }
                .buttonStyle(.borderedProminent).tint(Brand.orange).controlSize(.large)
                .disabled(dump.state == "structuring")
                .accessibilityIdentifier("dump.done")
            }
        }
        .padding(20)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Brand.orange.opacity(0.06), in: RoundedRectangle(cornerRadius: 24))
        .overlay(RoundedRectangle(cornerRadius: 24).stroke(Brand.orange.opacity(0.35)))
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
    let send: (String) async -> Bool
    let more: () async -> Void
    let read: () async -> Void
    let challenge: () async -> Void
    let discard: () async -> Void
    let close: () -> Void
    @State private var text = ""
    @State private var picked: String?
    @State private var sure = false
    @State private var discardSure = false
    @State private var busy = false
    @FocusState private var editing: Bool

    private var target: String? { BrainDumpCopy.target(dump, picked: picked, active: active, sessions: sessions) }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text(BrainDumpCopy.reviewLede).font(.subheadline).foregroundStyle(.secondary)
                    if dump.fallback == true {
                        Label(BrainDumpCopy.fallback, systemImage: "exclamationmark.triangle.fill").font(.footnote).foregroundStyle(Brand.orange)
                            .accessibilityIdentifier("dump.fallback")
                    }
                    TextEditor(text: $text)
                        .font(.body)
                        .frame(minHeight: 220)
                        .scrollContentBackground(.hidden)
                        .padding(10)
                        .background(Brand.card, in: RoundedRectangle(cornerRadius: 14))
                        .focused($editing)
                        .onChange(of: editing) { if !editing { Task { await saveEdit() } } }
                        .accessibilityIdentifier("dump.text")
                    // To: a field, like Mail's, so it never reads as a second button; Send is the one primary action.
                    Menu {
                        Picker("Session", selection: Binding(get: { target ?? "" }, set: { picked = $0; sure = false })) {
                            ForEach(sessions, id: \.self) { Text($0).tag($0) }
                        }
                    } label: {
                        HStack(spacing: 8) {
                            Text(BrainDumpCopy.to).foregroundStyle(.secondary)
                            Text(target ?? "").fontWeight(.semibold).foregroundStyle(.primary).lineLimit(1)
                            Spacer(minLength: 0)
                            Image(systemName: "chevron.up.chevron.down").font(.footnote.weight(.semibold)).foregroundStyle(.secondary)
                        }
                        .padding(.horizontal, 14).frame(minHeight: 46)
                        .background(Brand.card, in: RoundedRectangle(cornerRadius: 12))
                        .overlay(RoundedRectangle(cornerRadius: 12).stroke(.white.opacity(0.1)))
                    }
                    .tint(.primary)  // a field, not an accent: the orange is Send's
                    .accessibilityLabel("\(BrainDumpCopy.to) \(target ?? "")")
                    .accessibilityIdentifier("dump.session")
                    if let note = problem ?? dump.problem {
                        Label(note, systemImage: "exclamationmark.triangle.fill").font(.footnote).foregroundStyle(Brand.orange)
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
                            .font(.headline).frame(maxWidth: .infinity).padding(.vertical, 6)
                    }
                    .buttonStyle(.borderedProminent).tint(sure ? Brand.orange.mix(with: .black, by: 0.35) : Brand.orange).controlSize(.large)
                    .overlay(Capsule().stroke(Brand.orange, lineWidth: 2).padding(-4).opacity(sure ? 1 : 0))
                    .animation(.easeOut(duration: 0.15), value: sure)
                    .disabled(target == nil || busy)
                    .accessibilityLabel(sure ? BrainDumpCopy.sendSure : "\(BrainDumpCopy.sendTo) \(target ?? "")")
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
                        Text(discardSure ? BrainDumpCopy.discardSure : BrainDumpCopy.discard).font(.subheadline.weight(.semibold))
                            .padding(.horizontal, 16).padding(.vertical, 8)
                    }
                    .buttonStyle(.plain).foregroundStyle(.red)
                    .frame(maxWidth: .infinity).padding(.top, 6)
                    .accessibilityIdentifier("dump.discard")
                    Text(BrainDumpCopy.reviewHint).font(.footnote).foregroundStyle(.secondary)
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
            Text(title).font(.subheadline).lineLimit(1).minimumScaleFactor(0.8).frame(maxWidth: .infinity).frame(minHeight: 40)
                .overlay(Capsule().stroke(.white.opacity(0.18)))
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
