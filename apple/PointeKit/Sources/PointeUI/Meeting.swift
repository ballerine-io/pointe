import SwiftUI

// Meeting mode: Pointe sits in a meeting for one person, the owner. Listening: it never speaks and writes notes.
// Participating: it speaks only when asked, and otherwise raises a hand. Copy and behavior match the page
// (docs/design/2026-11-feature-plan.md, meeting mode, UX table).

enum MeetingCopy {
    /// Under the speakers: how to claim a line that was given to someone else (a context menu: long press, or right-click).
    static let notYouHere = "Not you? \(Surface.isMac ? "Right-click" : "Long-press") a line in the Transcript and choose \u{201C}That was me\u{201D}."
    static let listening = "Listening"
    static let participating = "Participating"
    static let listeningWhat = "Never speaks. Writes what matters into the notes: unanswered questions, decisions, action items."
    static let participatingWhat = "Speaks only when you ask. Otherwise it raises a hand, and you let it speak."
    static let consent = "Everyone in the room knows this is being transcribed and sent to the speech vendor"
    static let lede = "Pointe sits in and takes notes for you. It stays quiet unless you let it speak."  // the page's MEETING_COPY.lede

    /// A speaker's count in the Speakers sheet.
    static func turns(_ n: Int) -> String { n == 1 ? "1 turn" : "\(n) turns" }

    static func vendor(_ id: String?) -> String {
        switch id ?? "" {
        case "soniox": "Soniox"
        case "anthropic": "Anthropic"
        case "gemini": "Google Gemini"
        case "openai": "OpenAI"
        case "elevenlabs": "ElevenLabs"
        case "local": "this Mac"
        case "": "none"
        case let other: other
        }
    }

    static func mode(_ mode: String?) -> String { mode == "participating" ? participating : listening }

    /// Under "Send action items to…": this sheet's own send, else what the voice did (the page's end sheet says the same).
    static func sendLine(sent: String?, pending: API.Meeting.SendPending?, sentTo: String?) -> String? {
        if let sent { return sent }
        if let pending { return "Pointe asked: “\(pending.line)” Say yes, or send it here." }
        if let sentTo { return "Asked \(sentTo) to take them." }
        return nil
    }

    /// What the share sheet sends: the notes, and the transcript only when given one.
    static func markdown(result: API.MeetingResult, items: [API.ActionItem], notes: [API.Note],
                         transcript: [API.TranscriptTurn]) -> String {
        func filled(_ s: String?) -> String? { s.flatMap { $0.trimmingCharacters(in: .whitespaces).isEmpty ? nil : $0 } }
        var out = ["# Meeting notes", "", filled(result.summary) ?? "No summary."]
        if let d = result.decisions, !d.isEmpty { out += ["", "## Decisions"] + d.map { "- \($0)" } }
        if !items.isEmpty {
            out += ["", "## Action items"] + items.map { a in
                "- \(a.what)" + (filled(a.owner).map { " (owner: \($0))" } ?? "") + (filled(a.due).map { " (due: \($0))" } ?? "")
            }
        }
        if let q = result.open_questions, !q.isEmpty { out += ["", "## Open questions"] + q.map { "- \($0)" } }
        let answers = notes.filter { $0.kind == "answer" && $0.state != "dismissed" }
        if !answers.isEmpty { out += ["", "## Answers found"] + answers.map { "- \($0.text)" } }
        if !transcript.isEmpty {
            out += ["", "## Transcript"] + transcript.map { "- \($0.who ?? $0.speaker.map { "Speaker \($0)" } ?? "?"): \($0.text)" }
        }
        return out.joined(separator: "\n") + "\n"
    }
}

/// The notes of the meeting on now, kept in step with the Mac: fetched only when the status says they changed.
@MainActor @Observable
final class MeetingFeed {
    /// New notes after an id, and older ones changed after a version (nil: every changed one).
    typealias Fetch = (_ since: Int, _ changedSince: Int?) async throws -> API.NotesPage

    private(set) var notes: [API.Note] = []
    private(set) var transcript: [API.TranscriptTurn] = []
    private var version = -1        // the notes version of the last answer; below 0 the next fetch is whole
    private var since: Double = 0
    private var meetingId: String?  // the meeting the notes belong to (an older daemon names none)

    func sync(_ status: API.Status?, api: API) async {
        await sync(status) { since, changed in try await api.notes(since: since, changedSince: changed) }
    }

    func sync(_ status: API.Status?, fetch: Fetch) async {
        guard let meeting = status?.meeting, meeting.isOn || meeting.isEnded else {
            notes = []; transcript = []; version = -1; since = 0; meetingId = nil
            return
        }
        // A new meeting starts clean. An ended meeting's status has neither field: it keeps the ones it had.
        if meeting.isOn, (meeting.since ?? since) != since || (meeting.id != nil && meeting.id != meetingId) {
            since = meeting.since ?? since; meetingId = meeting.id; notes = []; transcript = []; version = -1
        }
        let fresh = status?.notes?.version ?? 0
        guard fresh != version else { return }
        let asked = version, whole = asked < 0, key = meetingId
        guard let page = try? await fetch(whole ? 0 : notes.map(\.id).max() ?? 0, whole ? nil : asked) else { return }
        // Answers can land out of order: one asked before a newer answer arrived would undo it (a suggestion you
        // accepted, open again). Only the answer to the version still held counts.
        guard version == asked, meetingId == key else { return }
        notes = Self.merge(whole ? [] : notes, page.notes ?? [], meeting: key, since: since)
        version = page.version ?? fresh
    }

    /// Changed notes replace their copy by id. Only this meeting's: never another meeting's, or one written outside a
    /// meeting. A note from an older daemon carries no meeting, and counts when written after the meeting started.
    static func merge(_ held: [API.Note], _ fresh: [API.Note], meeting: String?, since: Double) -> [API.Note] {
        var byId = Dictionary(uniqueKeysWithValues: held.map { ($0.id, $0) })
        for note in fresh {
            let ours = note.meeting.map { meeting == nil || $0 == meeting } ?? (meeting == nil && (note.at ?? since) >= since - 5)
            if ours { byId[note.id] = note }
        }
        return byId.values.sorted { $0.id < $1.id }
    }

    func loadTranscript(api: API) async {
        if let turns = try? await api.transcript() { transcript = turns }
    }

    /// Shown at once, before the Mac confirms.
    func setState(_ id: Int, _ state: String) {
        notes = notes.map { $0.id == id ? API.Note(id: $0.id, kind: $0.kind, at: $0.at, updated: $0.updated, text: $0.text,
                                                    meta: $0.meta, speakers: $0.speakers, session: $0.session, state: state,
                                                    meeting: $0.meeting, rev: $0.rev) : $0 }
    }

    func useDemo(_ demo: [API.Note]) { notes = demo }
}

// MARK: start

/// Two steps: what kind of meeting and its context, then who receives the room's audio. Nothing starts without the
/// consent step.
struct MeetingStartSheet: View {
    let sessions: [API.Session]
    let defaults: API.Prefs?
    let vendors: () async -> (API.VendorsReply?, String?)
    let start: (_ mode: String, _ brief: String, _ sessions: [String], _ autoLookups: Bool) async -> String?
    @Environment(\.dismiss) private var dismiss
    @State private var mode = "listening"
    @State private var brief = ""
    @State private var linked: Set<String> = []
    @State private var autoLookups = false
    @State private var step = 1
    @State private var reply: API.VendorsReply?
    @State private var agreed = false
    @State private var starting = false
    @State private var problem: String?
    @Environment(\.dynamicTypeSize) private var typeSize

    var body: some View {
        NavigationStack {
            BrandForm {
                if step == 1 { setup } else { consent }
                if let problem {
                    Label(problem, systemImage: "exclamationmark.triangle.fill").foregroundStyle(Brand.accent)
                }
            }
            .scrollContentBackground(.hidden)
            .sheetTitle(step == 1 ? "Start a meeting" : "Before it starts")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if step == 1 {
                        Button("Continue") { Task { await toConsent() } }.accessibilityIdentifier("meetingContinue")
                    } else {
                        Button("Start") { Task { await begin() } }
                            .disabled(!agreed || starting || reply?.soniox == false)
                            .accessibilityIdentifier("meetingStart")
                    }
                }
            }
        }
        .onAppear {
            mode = defaults?.defaultMode ?? "listening"
            autoLookups = defaults?.autoLookups ?? false
        }
    }

    @ViewBuilder private var setup: some View {
        Section {
            modeRow("listening", MeetingCopy.listening, MeetingCopy.listeningWhat, "ear")
            modeRow("participating", MeetingCopy.participating, MeetingCopy.participatingWhat, "hand.raised")
        } header: { Group { Text("Mode") }.brandKicker() } footer: {
            Group { Text(MeetingCopy.lede).accessibilityIdentifier("meetingLede") }.brandFootnote()
        }
        Section {
            TextField("Agenda, goals, names, anything it should know", text: $brief, axis: .vertical)
                .lineLimit(3...8)
                .accessibilityIdentifier("meetingBrief")
        } header: { Group { Text("Context") }.brandKicker() }
        if !sessions.isEmpty {
            Section {
                ForEach(sessions) { s in
                    Toggle(isOn: Binding(get: { linked.contains(s.name) },
                                         set: { on in if on { linked.insert(s.name) } else { linked.remove(s.name) } })) {
                        Text(s.name)
                    }
                    .tint(Brand.orange)
                }
                Toggle("Auto lookups", isOn: $autoLookups).tint(Brand.orange)
            } header: { Group { Text("Linked sessions") }.brandKicker() } footer: {
                Group {
                    Text(autoLookups ? "A question a linked session can answer is looked up at once, in a read-only copy."
                         : "A question a linked session can answer waits for your Look up tap.")
                }.brandFootnote()
            }
        }
    }

    private func modeRow(_ value: String, _ title: String, _ what: String, _ symbol: String) -> some View {
        let check = Image(systemName: mode == value ? "checkmark.circle.fill" : "circle")
            .foregroundStyle(mode == value ? Brand.accent : Brand.muted).font(.brand(.title3))
        return Button { mode = value } label: {
            if typeSize.isAccessibilitySize {  // one column: the explanation gets the whole width
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 10) { check; Text(title).font(.brand(.headline)).foregroundStyle(.primary) }
                    Text(what).font(.brand(.subheadline)).foregroundStyle(Brand.muted)
                }
            } else {
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: symbol).font(.brand(.title3)).foregroundStyle(Brand.accent).frame(width: 28)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(title).font(.brand(.headline)).foregroundStyle(.primary)
                        Text(what).font(.brand(.subheadline)).foregroundStyle(Brand.muted)
                    }
                    Spacer()
                    check
                }
            }
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("meetingMode-\(value)")
        .accessibilityAddTraits(mode == value ? .isSelected : [])
    }

    @ViewBuilder private var consent: some View {
        Section {
            vendorRow("waveform", "Room audio", reply?.vendors?.room_audio, "everyone's speech, to transcribe it")
            vendorRow("note.text", "Notes", reply?.vendors?.notes, "the transcript, to write the notes")
            vendorRow("speaker.wave.2", "Spoken replies", reply?.vendors?.speech, "what Pointe says, when it speaks")
            vendorRow("command", "Your commands", reply?.vendors?.commands, "what you ask it")
        } header: { Group { Text("Who receives what") }.brandKicker() } footer: {
            Group {
                Text("Nothing is stored on the Mac unless you export it at the end.")
            }.brandFootnote()
        }
        if reply?.soniox == false {
            Label("Meeting mode needs a Soniox key on the Mac: it tells the speakers apart.", systemImage: "key")
                .foregroundStyle(Brand.accent)
        }
        Section {
            Toggle(isOn: $agreed) { Text(MeetingCopy.consent).font(.brand(.subheadline)) }
                .tint(Brand.orange)
                .accessibilityIdentifier("meetingConsent")
        }
    }

    private func vendorRow(_ symbol: String, _ what: String, _ vendor: String?, _ detail: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: symbol).foregroundStyle(Brand.accent).frame(width: 24)
            VStack(alignment: .leading, spacing: 2) {
                Text(what).font(.brand(.subheadline, .semibold))
                Text(detail).font(.brand(.caption)).foregroundStyle(Brand.muted)
            }
            Spacer()
            Text(reply == nil ? "…" : MeetingCopy.vendor(vendor)).font(.brand(.subheadline)).foregroundStyle(Brand.muted)
        }
        .accessibilityElement(children: .combine)
    }

    private func toConsent() async {
        problem = nil
        let (got, why) = await vendors()
        reply = got
        problem = why
        if got != nil { withAnimation { step = 2 } }
    }

    private func begin() async {
        starting = true
        problem = await start(mode, brief.trimmingCharacters(in: .whitespacesAndNewlines), Array(linked), autoLookups)
        starting = false
        if problem == nil { dismiss() }
    }
}

// MARK: during

/// Always visible while the meeting is on: a red dot, the mode, who is in the room, how long, and where the audio goes.
struct MeetingBanner: View {
    let meeting: API.Meeting
    @Environment(\.dynamicTypeSize) private var typeSize
    let setMode: (String) -> Void
    let speakers: () -> Void
    let settings: () -> Void
    let reconnect: () -> Void

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            HStack(spacing: 10) {
                Circle().fill(Brand.danger).frame(width: 8, height: 8)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 2) {
                    // Large text wraps instead of cutting off where the audio goes.
                    if typeSize.isAccessibilitySize {
                        Text(line(context.date, full: true)).font(.brand(.subheadline, .semibold))
                            .fixedSize(horizontal: false, vertical: true)
                        Text(detail).font(.brand(.caption)).foregroundStyle(Brand.muted).fixedSize(horizontal: false, vertical: true)
                    } else {  // a narrow phone drops the speaker count before the timer, and the state before the vendor
                        ViewThatFits(in: .horizontal) {
                            Text(line(context.date, full: true))
                            Text(line(context.date, full: false))
                        }
                        .font(.brand(.subheadline, .semibold)).lineLimit(1)
                        ViewThatFits(in: .horizontal) {
                            Text(detail)
                            Text(vendorLine)
                        }
                        .font(.brand(.caption)).foregroundStyle(Brand.muted).lineLimit(1)
                    }
                }
                Spacer(minLength: 6)
                Menu {
                    Picker("Mode", selection: Binding(get: { meeting.mode ?? "listening" }, set: setMode)) {
                        Label(MeetingCopy.listening, systemImage: "ear").tag("listening")
                        Label(MeetingCopy.participating, systemImage: "hand.raised").tag("participating")
                    }
                    Button { speakers() } label: { Label("Speakers", systemImage: "person.2") }
                    Button { reconnect() } label: { Label("Reconnect audio", systemImage: "arrow.triangle.2.circlepath") }
                        .disabled(meeting.isEnding)
                    Button { settings() } label: { Label("Meeting settings", systemImage: "gearshape") }
                } label: {
                    Image(systemName: "slider.horizontal.3").font(.brand(.body, .semibold))
                        .frame(width: 34, height: 34).background(Brand.raised, in: Circle())
                }
                .accessibilityLabel("Meeting options")
            }
            .padding(.horizontal, 14).padding(.vertical, 10)
            .dynamicTypeSize(...DynamicTypeSize.accessibility2)  // pinned above the notes: past this it would push them away
            .background(Brand.danger.opacity(0.10), in: RoundedRectangle(cornerRadius: 16))
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.danger.opacity(0.45)))
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("meetingBanner")
    }

    private func line(_ now: Date, full: Bool) -> String {
        let count = meeting.speakers?.count ?? 0
        return ["Meeting", MeetingCopy.mode(meeting.mode), full && count > 0 ? "\(count) speaker\(count == 1 ? "" : "s")" : nil,
                elapsed(now)]
            .compactMap { $0 }.joined(separator: " · ")
    }

    /// Where the audio goes stays on screen however narrow the phone: it never truncates away.
    private var vendorLine: String { "audio to \(MeetingCopy.vendor(meeting.vendors?.room_audio))" }
    private var detail: String { vendorLine + " · " + state }

    private var state: String {
        if meeting.isEnding { return "Ending: writing the summary\u{2026}" }
        if meeting.speaking == true { return "Speaking to the room" }
        if meeting.owner_known != true { return "Say \u{201C}Pointe, that's me\u{201D}" }
        if meeting.paused == true { return "Quiet room" }
        return meeting.participating ? "It speaks only when you ask" : "It never speaks"
    }

    private func elapsed(_ now: Date) -> String {
        let secs = max(0, Int(now.timeIntervalSince1970 - (meeting.since ?? now.timeIntervalSince1970)))
        return secs >= 3600 ? String(format: "%d:%02d:%02d", secs / 3600, secs / 60 % 60, secs % 60)
            : String(format: "%02d:%02d", secs / 60, secs % 60)
    }
}

/// It has something to say. Participating: let it speak, not now, or type it instead. Listening: a highlighted note.
struct HandCard: View {
    let hand: API.Hand
    let participating: Bool
    let decide: (String) async -> Void
    @State private var busy = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label { Text("Wants to say: ") + Text(TextDirection.isolated(hand.line)).bold() } icon: {
                Image(systemName: "hand.raised.fill").foregroundStyle(Brand.accent)
            }
            .font(.brand(.subheadline))
            ViewThatFits(in: .horizontal) {  // side by side when they fit; stacked at large text sizes
                HStack(spacing: 8) { buttons }.lineLimit(1).minimumScaleFactor(0.85)  // a hair short of fitting: smaller, not cut
                VStack(spacing: 8) { buttons }
            }
            .font(.brand(.subheadline, .semibold))
            .controlSize(.regular)
            .disabled(busy)
        }
        .padding(14)
        .dynamicTypeSize(...DynamicTypeSize.accessibility2)  // it sits over the notes: past this it would hide them all
        .background(Brand.card, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.orangeLine))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("handCard")
    }

    @ViewBuilder private var buttons: some View {
        if participating {
            Button { act("speak") } label: { Text("Let it speak").frame(maxWidth: .infinity) }
                .buttonStyle(.brandPrimary).accessibilityIdentifier("handSpeak")
        }
        Button { act("later") } label: { Text("Not now").frame(maxWidth: .infinity) }
            .buttonStyle(.brandQuiet).accessibilityIdentifier("handLater")
        Button { act("type") } label: { Text("Type it instead").frame(maxWidth: .infinity) }
            .buttonStyle(.brandQuiet).accessibilityIdentifier("handType")
    }

    private func act(_ decision: String) {
        busy = true
        Task { await decide(decision); busy = false }
    }
}

/// The notes stream: thoughts, questions, answers found, decisions, action items; and the transcript, off by default.
struct NotesFeed: View {
    enum Filter: String, CaseIterable, Identifiable {
        case all = "All", thoughts = "Thoughts", questions = "Questions", answers = "Answers", actions = "Actions"
        case transcript = "Transcript"
        var id: String { rawValue }
        func keeps(_ kind: String) -> Bool {
            switch self {
            case .all: true
            case .thoughts: kind == "thought" || kind == "hand"
            case .questions: kind == "question"
            case .answers: kind == "answer"
            case .actions: kind == "action" || kind == "decision"
            case .transcript: false
            }
        }
    }

    let notes: [API.Note]
    let transcript: [API.TranscriptTurn]
    let speakers: [API.Speaker]
    @Binding var filter: Filter
    let lookUp: (API.Note) -> Void
    let setState: (API.Note, String) -> Void
    let accept: (API.Note) -> Void
    let thatWasMe: (API.TranscriptTurn) -> Void
    let showTranscript: () -> Void

    private var shown: [API.Note] {
        notes.filter { $0.state != "dismissed" && filter.keeps($0.kind) && $0.kind != "summary" && !settled($0) }
    }

    /// An open suggestion for a speaker who already has that name (a repeat of one you accepted) asks nothing.
    private func settled(_ note: API.Note) -> Bool {
        guard note.kind == "speaker", note.state == "open", let label = note.meta?.label, let name = note.meta?.name else { return false }
        return speakers.contains { $0.label == label && $0.name == name }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(Filter.allCases) { f in
                        Button {
                            filter = f
                            if f == .transcript { showTranscript() }
                        } label: {
                            Text(f.rawValue).font(.brand(.subheadline, .medium))
                                .padding(.horizontal, 12).padding(.vertical, 7)
                                .background(filter == f ? AnyShapeStyle(Brand.tint) : AnyShapeStyle(Brand.raised),
                                            in: Capsule())
                                .overlay(Capsule().stroke(filter == f ? Brand.orangeLine : .clear))
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("notesFilter-\(f.rawValue)")
                        .accessibilityAddTraits(filter == f ? .isSelected : [])
                    }
                }
            }
            .edgeFade()
            if filter == .transcript {
                transcriptView
            } else if shown.isEmpty {
                EmptyNote(title: "Nothing noted yet", symbol: "note.text",
                          text: "Questions nobody answered, decisions and action items show up here as the meeting goes.")
                    .padding(.top, 30)
            } else {
                LazyVStack(spacing: 10) {
                    ForEach(shown) { note in
                        NoteRow(note: note, lookUp: lookUp, setState: setState, accept: accept)
                            .transition(.move(edge: .bottom).combined(with: .opacity))
                    }
                }
                .animation(.snappy, value: shown.map(\.id))
            }
        }
        .sensoryFeedback(.selection, trigger: notes.filter { $0.kind == "question" }.count)
        .accessibilityIdentifier("notesFeed")
    }

    @ViewBuilder private var transcriptView: some View {
        if transcript.isEmpty {
            Text("Nothing heard yet. The transcript stays in memory on the Mac and is never stored unless you export it.")
                .font(.brand(.footnote)).foregroundStyle(Brand.muted).padding(.top, 20)
        } else {
            LazyVStack(alignment: .leading, spacing: 8) {
                ForEach(transcript) { turn in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(who(turn)).font(.brand(.caption, .semibold)).foregroundStyle(Brand.accent)
                        Text(turn.text).readingDirection(of: turn.text).font(.brand(.callout))
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
                    .background(Brand.card, in: RoundedRectangle(cornerRadius: 12))
                    .contextMenu {
                        Button { thatWasMe(turn) } label: { Label("That was me", systemImage: "person.crop.circle.badge.checkmark") }
                    }
                }
            }
        }
    }

    /// The Mac sends the name it knows; a label it later learned a name for is looked up here.
    private func who(_ turn: API.TranscriptTurn) -> String {
        if let s = speakers.first(where: { $0.label == turn.speaker }), s.is_owner == true || s.name?.isEmpty == false { return s.shown }
        return turn.who ?? "Speaker \(turn.speaker ?? "?")"
    }
}

struct NoteRow: View {
    let note: API.Note
    let lookUp: (API.Note) -> Void
    let setState: (API.Note, String) -> Void
    let accept: (API.Note) -> Void

    private var done: Bool { note.state == "done" }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: symbol).foregroundStyle(tint).frame(minWidth: 18)
                Text(kindLabel).font(.brand(.caption, .semibold)).foregroundStyle(tint)
                Spacer()
                if let at = note.at {
                    Text(Date(timeIntervalSince1970: at), style: .time).font(.brand(.caption2)).foregroundStyle(Brand.muted)
                }
            }
            Text(note.text).readingDirection(of: note.text).font(.brand(.callout)).strikethrough(done).foregroundStyle(done ? Brand.muted : .primary)
                .lineLimit(note.kind == "session_news" ? 2 : nil)
            if let extra { Text(extra).font(.brand(.caption)).foregroundStyle(Brand.muted) }
            actions
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Brand.card, in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(note.kind == "question" && note.state != "done" ? tint.opacity(0.5) : .clear))
        .contextMenu {
            if !done { Button { setState(note, "done") } label: { Label("Done", systemImage: "checkmark") } }
            Button(role: .destructive) { setState(note, "dismissed") } label: { Label("Dismiss", systemImage: "xmark") }
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("note-\(note.kind)")
    }

    @ViewBuilder private var actions: some View {
        if note.kind == "speaker", note.state != "done" {
            HStack(spacing: 8) {
                Button("Use this name") { accept(note) }.buttonStyle(.brandPrimary)
                Button("Ignore") { setState(note, "dismissed") }.buttonStyle(.brandQuiet)
            }
            .controlSize(.small)
        } else if note.meta?.lookup != nil, note.state == "open" {
            Button { lookUp(note) } label: {
                Label("Look up in \(note.meta?.lookup?.session ?? "the session")", systemImage: "magnifyingglass")
            }
            .buttonStyle(.brandQuiet).controlSize(.small)
            .accessibilityIdentifier("lookUp")
        }
    }

    private var extra: String? {
        switch note.kind {
        case "action":
            let parts = [note.meta?.owner.flatMap { $0.isEmpty ? nil : "owner: \($0)" },
                         note.meta?.due.flatMap { $0.isEmpty ? nil : "due: \($0)" }].compactMap { $0 }
            return parts.isEmpty ? nil : parts.joined(separator: " · ")
        case "question": return note.meta?.asked_by.flatMap { $0.isEmpty ? nil : "asked by \($0)" }
        case "answer": return note.session.map { "from \($0)" }
        case "hand": return note.meta?.full.flatMap { $0 == note.text || $0.isEmpty ? nil : $0 }
        default: return nil
        }
    }

    private var kindLabel: String {
        switch note.kind {
        case "thought": "Thought"
        case "question": "Open question"
        case "answer": "Answer found"
        case "action": "Action item"
        case "decision": "Decision"
        case "hand": "Wanted to say"
        case "session_news": "Session news"
        case "brief": "Brief"
        case "speaker": "Speaker"
        default: note.kind.capitalized
        }
    }

    private var symbol: String {
        switch note.kind {
        case "thought": "lightbulb"
        case "question": "questionmark.circle"
        case "answer": "checkmark.seal"
        case "action": "checklist"
        case "decision": "flag"
        case "hand": "hand.raised"
        case "session_news": "tray"
        case "brief": "doc.text"
        case "speaker": "person.crop.circle.badge.questionmark"
        default: "note.text"
        }
    }

    private var tint: Color {
        switch note.kind {
        case "question": Brand.accent
        case "answer": Brand.successText
        case "action", "decision": Brand.text
        case "hand": Brand.accent
        default: Brand.muted
        }
    }
}

/// The meeting's controls: mode, ask, the mic, speakers, end.
struct MeetingBar: View {
    let meeting: API.Meeting
    let phase: Call.State
    let muted: Bool
    let typing: Bool
    let mic: () -> Void
    let toggleMode: () -> Void
    let ask: () -> Void
    let speakers: () -> Void
    let end: () -> Void
    var talk: RingTalk? = nil  // push to talk: hold the ring

    var body: some View {
        HStack(spacing: 0) {
            side(meeting.participating ? "Participating" : "Listening",
                 meeting.participating ? "hand.raised.fill" : "ear", on: meeting.participating, action: toggleMode)
                .accessibilityIdentifier("meetingModeToggle")
            Spacer()
            side("Ask", typing ? "keyboard.chevron.compact.down" : "keyboard", on: typing, action: ask)
            Spacer()
            Button(action: mic) {
                ZStack {
                    Circle().fill(hot ? Brand.danger : Brand.raised)
                    Image(systemName: hot ? "mic.fill" : phase == .live ? "mic.slash.fill" : "mic")
                        .font(.system(size: 26, weight: .semibold))
                        .foregroundStyle(hot ? Color.white : Brand.dim)
                        .contentTransition(.symbolEffect(.replace))
                    if phase == .connecting || phase == .reconnecting { ProgressView().tint(Brand.muted).offset(y: 30) }
                }
                .frame(width: 70, height: 70)
            }
            .buttonStyle(.plain)
            .disabled(phase != .live)
            .accessibilityIdentifier("micRing")
            .accessibilityLabel(phase == .live ? (muted ? "Unmute" : "Mute") : phase == .off ? "Microphone" : "Connecting")
            .accessibilityHint(phase == .off ? "\(ConnectCopy.connectFirst): the meeting runs on the Mac's call; Connect joins it from the phone" : "")
            .ringTalk(phase == .live ? talk : nil)
            Spacer()
            side("Speakers", "person.2", action: speakers)
            Spacer()
            side(meeting.isEnding ? "Ending\u{2026}" : "End", "stop.circle.fill", tint: Brand.dangerText, action: end)
                .disabled(meeting.isEnding)
                .accessibilityIdentifier("endMeeting")
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .brandCard()
        .dynamicTypeSize(...DynamicTypeSize.large)
        .sensoryFeedback(.impact(weight: .light), trigger: meeting.mode)
    }

    private var hot: Bool { phase == .live && (talk?.talking ?? !muted) }

    private func side(_ label: String, _ symbol: String, on: Bool = false, tint: Color = .primary,
                      action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: 4) {
                Image(systemName: symbol).font(.system(size: 19, weight: .medium))
                    .frame(width: 46, height: 46)
                    .background(on ? AnyShapeStyle(Brand.tint) : AnyShapeStyle(Brand.raised), in: Circle())
                Text(label).font(.brand(.caption2)).lineLimit(1).fixedSize()
            }
            .foregroundStyle(tint)
            .dynamicTypeSize(...DynamicTypeSize.xxLarge)  // five controls in one row: the labels cannot grow without bound
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}

/// Name the people in the room. Names are applied only by the owner.
struct SpeakersSheet: View {
    let speakers: [API.Speaker]
    let rename: (String, String) async -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var names: [String: String] = [:]

    var body: some View {
        NavigationStack {
            BrandForm {
                Section {
                    if speakers.isEmpty { Text("Nobody heard yet.").foregroundStyle(Brand.muted) }
                    ForEach(speakers) { s in
                        HStack {
                            Text(s.is_owner == true ? "You" : "Speaker \(s.label)").frame(width: 92, alignment: .leading)
                                .foregroundStyle(Brand.muted)
                            TextField("Name", text: Binding(get: { names[s.label] ?? (s.name ?? "") }, set: { names[s.label] = $0 }))
                                .disabled(s.is_owner == true)
                            Text(MeetingCopy.turns(s.turns ?? 0)).font(.brand(.caption)).foregroundStyle(Brand.muted)
                                .lineLimit(1).fixedSize()
                        }
                    }
                } footer: {
                    Group {
                        Text(MeetingCopy.notYouHere)
                    }.brandFootnote()
                }
            }
            .scrollContentBackground(.hidden)
            .sheetTitle("Speakers")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        Task {
                            for (label, name) in names where !name.trimmingCharacters(in: .whitespaces).isEmpty {
                                await rename(label, name.trimmingCharacters(in: .whitespaces))
                            }
                            dismiss()
                        }
                    }
                }
            }
        }
    }
}

// MARK: end

/// The summary and what to do with it. Nothing leaves the Mac or reaches a session unless you choose it here.
struct MeetingEndSheet: View {
    let result: API.MeetingResult
    /// What the voice did with the action items, from the Mac: a read-back waiting for a yes, or where they went.
    var sendPending: API.Meeting.SendPending? = nil
    var sentTo: String? = nil
    let notes: [API.Note]
    let sessions: [API.Session]
    let transcript: () async -> [API.TranscriptTurn]
    let save: (Bool) async -> String?
    let send: (String) async -> String?  // nil when asked; otherwise why not
    let discard: () async -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var withTranscript = false
    @State private var turns: [API.TranscriptTurn] = []
    @State private var loadingTurns = false
    @State private var saved: String?
    @State private var sendTo: String?
    @State private var sent: String?
    @State private var confirmDiscard = false
    @State private var wholeSummary = false

    var body: some View {
        NavigationStack {
            BrandList {
                KickerSection("Summary") {  // a long summary is folded, so the export is not pages away
                    Text(result.summary ?? "No summary.").readingDirection(of: result.summary ?? "").font(.brand(.callout)).lineLimit(wholeSummary ? nil : 6)
                    if (result.summary ?? "").count > 320 {
                        Button(wholeSummary ? "Show less" : "Show all") { withAnimation { wholeSummary.toggle() } }
                            .font(.brand(.callout))
                    }
                }
                if let decisions = result.decisions, !decisions.isEmpty {
                    KickerSection("Decisions") { ForEach(decisions, id: \.self) { d in Label { Text(d).readingDirection(of: d) } icon: { Image(systemName: "flag") } } }
                }
                if !actionItems.isEmpty {
                    KickerSection("Action items") {
                        ForEach(actionItems, id: \.self) { a in
                            let who = [a.owner.flatMap { $0.isEmpty ? nil : $0 }, a.due.flatMap { $0.isEmpty ? nil : "due \($0)" }]
                                .compactMap { $0 }.joined(separator: " · ")
                            Label {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(a.what).readingDirection(of: a.what)
                                    if !who.isEmpty { Text(who).font(.brand(.caption)).foregroundStyle(Brand.muted) }
                                }
                            } icon: { Image(systemName: "checklist") }
                        }
                    }
                }
                if let open = result.open_questions, !open.isEmpty {
                    KickerSection("Open questions") { ForEach(open, id: \.self) { q in Label { Text(q).readingDirection(of: q) } icon: { Image(systemName: "questionmark.circle") } } }
                }
                Section {
                    Toggle("Include the transcript", isOn: $withTranscript).tint(Brand.orange)
                        .accessibilityIdentifier("exportTranscript")
                        .onChange(of: withTranscript) { _, on in
                            guard on else { return }
                            loadingTurns = true
                            Task { turns = await transcript(); loadingTurns = false }
                        }
                    ShareLink(item: markdown, subject: Text("Meeting notes")) {
                        Label(loadingTurns ? "Getting the transcript…" : "Share", systemImage: "square.and.arrow.up")
                    }
                    .disabled(loadingTurns)  // a share before the transcript arrives would silently leave it out
                    .accessibilityIdentifier("meetingShare")
                    Button { Task { saved = await save(withTranscript) } } label: {
                        Label("Save on the Mac", systemImage: "desktopcomputer")
                    }
                    .accessibilityIdentifier("meetingSave")
                    if let saved { Text(saved.isEmpty ? "Could not save." : "Saved: \(saved)").font(.brand(.caption)).foregroundStyle(Brand.muted) }
                } header: { Group { Text("Export") }.brandKicker() } footer: {
                    Group {
                        Text(withTranscript ? "With the transcript: everything that was said." : "Notes only: the transcript stays out.")
                    }.brandFootnote()
                }
                if !actionItems.isEmpty && !sessions.isEmpty {
                    Section {
                        Menu {
                            ForEach(sessions) { s in Button(s.name) { sendTo = s.name } }
                        } label: { Label("Send action items to…", systemImage: "paperplane") }
                        .accessibilityIdentifier("meetingSend")
                        if let line = MeetingCopy.sendLine(sent: sent, pending: sendPending, sentTo: sentTo) {
                            Text(line).font(.brand(.caption)).foregroundStyle(Brand.muted).accessibilityIdentifier("meetingSent")
                        }
                    } footer: { Group { Text("They go to the session as listed here, after you confirm.") }.brandFootnote() }
                }
                Section {
                    Button("Discard the meeting", role: .destructive) { confirmDiscard = true }
                        .accessibilityIdentifier("meetingDiscard")
                } footer: { Group { Text("Forgets the notes and the transcript on the Mac.") }.brandFootnote() }
            }
            .scrollContentBackground(.hidden)
            .sheetTitle("Meeting ended")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Close") { dismiss() } } }
            .alert("Send \(actionItems.count) action item\(actionItems.count == 1 ? "" : "s") to \(sendTo ?? "")?",
                   isPresented: Binding(get: { sendTo != nil }, set: { if !$0 { sendTo = nil } })) {
                Button("Send") {
                    let to = sendTo ?? ""
                    Task { sent = await send(to).map { "Not sent. \($0)" } ?? "Asked \(to) to take them." }
                    sendTo = nil
                }
                Button("Cancel", role: .cancel) { sendTo = nil }
            }
            .confirmationDialog("Discard the meeting? Its notes and transcript are forgotten.", isPresented: $confirmDiscard,
                                titleVisibility: .visible) {
                Button("Discard", role: .destructive) { Task { await discard(); dismiss() } }
            }
        }
        .accessibilityIdentifier("meetingEndSheet")
    }

    private var actionItems: [API.ActionItem] {
        if let items = result.action_items, !items.isEmpty { return items }
        return notes.filter { $0.kind == "action" && $0.state != "dismissed" }
            .map { API.ActionItem(what: $0.text, owner: $0.meta?.owner, due: $0.meta?.due) }
    }

    private var markdown: String {
        MeetingCopy.markdown(result: result, items: actionItems, notes: notes, transcript: withTranscript ? turns : [])
    }
}

// MARK: settings

struct MeetingSettingsSheet: View {
    let load: () async -> API.Prefs?
    let save: ([String: any Sendable]) async -> Bool
    @Environment(\.dismiss) private var dismiss
    @State private var prefs: API.Prefs?
    @State private var loaded = false

    var body: some View {
        NavigationStack {
            BrandForm {
                if var p = prefs {
                    Section {
                        Picker("Starts in", selection: Binding(get: { p.defaultMode }, set: { p.defaultMode = $0; update(p, ["meeting.default_mode": $0]) })) {
                            Text(MeetingCopy.listening).tag("listening")
                            Text(MeetingCopy.participating).tag("participating")
                        }
                        Toggle("Auto lookups", isOn: Binding(get: { p.autoLookups }, set: { p.autoLookups = $0; update(p, ["meeting.auto_lookups": $0]) }))
                            .tint(Brand.orange)
                        Picker("Notes in", selection: Binding(get: { p.notesLanguage }, set: { p.notesLanguage = $0; update(p, ["meeting.notes_language": $0]) })) {
                            Text("The meeting's language").tag("auto")
                            Text("English").tag("en")
                            Text("Hebrew").tag("he")
                        }
                    } footer: {
                        Group {
                            Text("Auto lookups: a question a linked session can answer is looked up at once, in a read-only copy. Off: it waits for your tap.")
                        }.brandFootnote()
                    }
                    Section {
                        LabeledContent("Consent step", value: p.consented ? "Accepted on this Mac" : "Not yet")
                        if p.consented {
                            Button("Ask again before the next meeting") { p.consented = false; update(p, ["meeting.consented": false]) }
                        }
                    } footer: { Group { Text("A voice start (\u{201C}meeting mode, listening\u{201D}) needs the consent step accepted once.") }.brandFootnote() }
                } else if loaded {
                    Label("The Mac did not send its meeting settings. Is Pointe on the Mac up to date and reachable?",
                          systemImage: "exclamationmark.triangle.fill").foregroundStyle(Brand.accent)
                } else {
                    ProgressView()
                }
            }
            .scrollContentBackground(.hidden)
            .sheetTitle("Meeting settings")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .task { prefs = await load(); loaded = true }
        }
    }

    private func update(_ p: API.Prefs, _ change: [String: any Sendable]) {
        prefs = p
        Task { if !(await save(change)) { prefs = await load() } }
    }
}
