import LocalAuthentication
import SwiftUI

/// The call: who you are talking to, what was said, what needs you, and the controls, with the mic at your thumb.
struct CallView: View {
    let pairing: Pairing
    let unpair: () -> Void
    @State private var call: Call
    @State private var status: API.Status?
    @State private var reachable = true
    @State private var problem: String?
    @State private var showSessions = false
    @State private var editing: API.Turn?
    @State private var typing = false
    @State private var atBottom = true
    @State private var unseen = false
    @State private var brainstormWanted: Bool?  // shown at once on a tap, before the Mac confirms
    @State private var feed = MeetingFeed()
    @State private var noteFilter = NotesFeed.Filter.all
    @State private var showMeetingStart = false
    @State private var showMeetingSettings = false
    @State private var showSpeakers = false
    @State private var confirmEnd = false
    @State private var meetingSince: Double?  // the meeting on now, or the one that just ended (its status drops `since`)
    @State private var closedEnd: Double?     // the ended meeting whose sheet you closed: not shown again unless asked
    @State private var prefs: API.Prefs?
    private let demo: Demo?

    init(pairing: Pairing, unpair: @escaping () -> Void, demo: Demo? = nil) {
        self.pairing = pairing
        self.unpair = unpair
        self.demo = demo
        _call = State(initialValue: Call(pairing: pairing))
        _status = State(initialValue: demo?.status)
        _showSessions = State(initialValue: demo?.screen == .sessions)
        _editing = State(initialValue: demo?.screen == .edit ? demo?.status.talk?.last(where: \.mine) : nil)
        _typing = State(initialValue: demo?.screen == .typing)
        _showMeetingStart = State(initialValue: demo?.screen == .meetingStart)
    }

    /// What the screen shows: the demo fixture is always live.
    private var phase: Call.State { demo == nil ? call.state : .live }
    private var live: Bool { phase == .live || phase == .reconnecting }
    private var muted: Bool { demo == nil ? call.muted : false }
    private var speaking: Bool { demo == nil ? call.botSpeaking : false }

    private var brainstorming: Bool { brainstormWanted ?? (status?.monologue != nil) }
    private var hearing: String { status?.hearing ?? "" }

    private var meeting: API.Meeting? { status?.meeting }

    var body: some View {
        Group {
            if let meeting, meeting.isOn {
                meetingScreen(meeting)
            } else if brainstorming {
                BrainstormPanel(said: status?.monologue?.said ?? "", hearing: hearing, back: { setBrainstorm(false) })
                    .padding(.horizontal, 14).padding(.vertical, 8)
                    .transition(.opacity.combined(with: .scale(scale: 0.98)))
                    .safeAreaInset(edge: .top, spacing: 0) { top }
                    .safeAreaInset(edge: .bottom, spacing: 0) { bottom }
            } else {
                chat
            }
        }
        .animation(.smooth(duration: 0.3), value: brainstorming)
        .background(Brand.background.ignoresSafeArea())
        .sheet(isPresented: $showSessions) {
            SessionsSheet(status: status, switchTo: focus, disconnect: disconnect, setMode: setMode)
                .presentationDetents([.medium, .large])
                .presentationBackground(.regularMaterial)
        }
        .sheet(item: $editing) { turn in
            EditTurnSheet(turn: turn) { text in await correct(turn, text) }
                .presentationDetents([.medium])
                .presentationBackground(.regularMaterial)
        }
        .sheet(isPresented: $showMeetingStart) {
            MeetingStartSheet(sessions: status?.sessions ?? [], defaults: prefs, vendors: meetingVendors, start: startMeeting)
                .presentationBackground(.regularMaterial)
        }
        .sheet(isPresented: $showMeetingSettings) {
            MeetingSettingsSheet(load: loadPrefs, save: savePrefs).presentationDetents([.medium, .large])
                .presentationBackground(.regularMaterial)
        }
        .sheet(isPresented: $showSpeakers) {
            SpeakersSheet(speakers: meeting?.speakers ?? []) { label, name in
                await act { try await call.api.nameSpeaker(label, name) }
            }
            .presentationDetents([.medium])
            .presentationBackground(.regularMaterial)
        }
        .sheet(isPresented: endSheetShown) {
            if let result = meeting?.result {
                MeetingEndSheet(result: result, notes: feed.notes, sessions: status?.sessions ?? [],
                                transcript: { (try? await call.api.transcript()) ?? [] },
                                save: { with in demo != nil ? "~/.claude-voice/meetings/demo.md" : (try? await call.api.exportMeeting(transcript: with)) ?? "" },
                                send: { to in await act { try await call.api.sendActions(to: to) } },
                                discard: { await act { try await call.api.discardMeeting() } })
                    .presentationBackground(.regularMaterial)
            }
        }
        .confirmationDialog("End the meeting? Pointe stops listening and writes the summary.", isPresented: $confirmEnd,
                            titleVisibility: .visible) {
            Button("End meeting", role: .destructive) { Task { await act { _ = try await call.api.endMeeting() } } }
                .accessibilityIdentifier("confirmEndMeeting")
        }
        .sensoryFeedback(.warning, trigger: meeting?.hand?.at) { _, new in new != nil }
        .onChange(of: "\(meeting?.since ?? 0)|\(status?.notes?.version ?? -1)|\(meeting?.isEnded == true)|\(noteFilter == .transcript ? meeting?.turns ?? 0 : 0)") {
            if let since = meeting?.since { meetingSince = since }
            guard demo == nil else { return }
            Task {
                await feed.sync(status, api: call.api)
                if noteFilter == .transcript { await feed.loadTranscript(api: call.api) }  // new turns, while you read them
            }
        }
        .task {
            if let demo { feed.useDemo(demo.notes); return }
            prefs = try? await call.api.prefs()
        }
        .task { if demo == nil { await poll() } }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active, demo == nil { Task { await call.resume() } }  // back from the background: redial if it dropped
        }
    }

    // MARK: pieces

    /// Pinned to the newest line while you are at the bottom; left alone, with a "New" pill, once you scroll up to read.
    private var chat: some View {
        ScrollViewReader { scroller in
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    ConversationView(turns: status?.talk ?? [], polish: status?.polish ?? false, hearing: hearing) { editing = $0 }
                    if let problem = problem ?? call.problem {
                        Label(problem, systemImage: "exclamationmark.triangle.fill")
                            .font(.footnote).foregroundStyle(Brand.orange).padding(.bottom, 8)
                    }
                    Color.clear.frame(height: 1).id("end")
                }
                .padding(.horizontal, 16)
                .padding(.top, 10)
            }
            .scrollDismissesKeyboard(.interactively)
            .accessibilityIdentifier("conversation")
            .defaultScrollAnchor(.bottom, for: .initialOffset)  // only where it starts: growing content must not pull you down
            .defaultScrollAnchor(.top, for: .sizeChanges)
            .onScrollGeometryChange(for: Bool.self) { geo in
                geo.visibleRect.maxY >= geo.contentSize.height - 48  // the visible part, insets included
            } action: { _, bottom in
                atBottom = bottom
                if bottom { unseen = false }
            }
            .onChange(of: "\(status?.talk?.last?.id ?? -1)|\(hearing)") {
                if atBottom {
                    withAnimation(.smooth(duration: 0.3)) { scroller.scrollTo("end", anchor: .bottom) }
                } else {
                    unseen = true
                }
            }
            .overlay(alignment: .bottom) {
                if unseen && !atBottom {
                    Button {
                        withAnimation(.smooth) { scroller.scrollTo("end", anchor: .bottom) }
                    } label: {
                        Label("New", systemImage: "arrow.down").font(.subheadline.weight(.semibold))
                            .padding(.horizontal, 14).padding(.vertical, 8)
                            .background(.thinMaterial, in: Capsule())
                            .overlay(Capsule().stroke(Brand.orange.opacity(0.6)))
                    }
                    .buttonStyle(.plain)
                    .padding(.bottom, 8)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                }
            }
            .animation(.snappy, value: unseen && !atBottom)
            .safeAreaInset(edge: .top, spacing: 0) { top }
            .safeAreaInset(edge: .bottom, spacing: 0) { bottom }
        }
    }

    private var top: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .center) {
                BrandHeader()
                Spacer()
                Button { openMeetingStart() } label: {
                    Image(systemName: "person.3.fill").font(.subheadline.weight(.semibold))
                        .frame(width: 36, height: 36).background(.thinMaterial, in: Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Start a meeting")
                .accessibilityIdentifier("startMeeting")
                menu
            }
            SessionChips(sessions: status?.sessions ?? [], active: status?.active, mode: status?.mode,
                         focus: focus, orchestrate: { setMode("orchestrator") }, disconnect: disconnect,
                         showAll: { showSessions = true })
            StatusLine(title: title, subtitle: subtitle, phase: phase, muted: muted, speaking: speaking)
        }
        .padding(.horizontal, 18)
        .padding(.top, 8)
        .padding(.bottom, 10)
        .background(.bar)
    }

    private var menu: some View {
        Menu {
            Toggle(isOn: Binding(get: { status?.polish ?? false }, set: { on in Task { await setPolish(on) } })) {
                Label("Clean up my words", systemImage: "wand.and.sparkles")
            }
            Button { showSessions = true } label: { Label("Sessions and mode", systemImage: "rectangle.stack") }
            if meeting?.isOn != true {
                Button { openMeetingStart() } label: { Label("Start a meeting", systemImage: "person.3") }
            }
            if meeting?.isEnded == true {
                Button { closedEnd = nil } label: { Label("The meeting that ended", systemImage: "doc.text") }
                    .accessibilityIdentifier("reopenMeetingEnd")
            }
            Button { showMeetingSettings = true } label: { Label("Meeting settings", systemImage: "gearshape") }
            Divider()
            Button("Unpair this phone", systemImage: "iphone.slash", role: .destructive) { call.hangUp(); unpair() }
        } label: {
            Image(systemName: "ellipsis").font(.body.weight(.semibold))
                .frame(width: 36, height: 36).background(.thinMaterial, in: Circle())
        }
        .accessibilityLabel("Settings")
    }

    private var bottom: some View {
        VStack(spacing: 10) {
            // What needs you sits by your thumb, never scrolled away under the conversation.
            if let request = waiting.first {
                RequestCard(session: request, showAgent: (status?.sessions ?? []).mixesAgents, answer: answer)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                if waiting.count > 1 {
                    Text("\(waiting.count - 1) more waiting").font(.caption).foregroundStyle(.secondary)
                }
            }
            if typing {
                TypeBar(send: say) { withAnimation(.snappy) { typing = false } }
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
            BottomBar(phase: phase, muted: muted, monologue: brainstorming, typing: typing,
                      mic: micTapped, listen: { setBrainstorm(!brainstorming) }, type: { withAnimation(.snappy) { typing.toggle() } },
                      sessions: { showSessions = true }, hangUp: { call.hangUp() })
        }
        .padding(.horizontal, 14)
        .padding(.top, 8)
        .padding(.bottom, 4)
        .animation(.snappy, value: waiting.first?.request_id)
    }

    private var waiting: [API.Session] { status?.sessions.filter { $0.waiting && $0.canApprove } ?? [] }

    @Environment(\.scenePhase) private var scenePhase

    /// The link to the Mac, from the call's own heartbeat: shown so "connected" is never a guess.
    private var health: String {
        guard phase == .live, demo == nil else { return "" }
        let quiet = Date().timeIntervalSince(call.lastHeard)
        if quiet > 3 { return " · no answer for \(Int(quiet)) s" }
        return call.rttMs.map { " · \($0) ms" } ?? ""
    }

    private var title: String {
        switch phase {
        case .off: return reachable ? "Not connected" : "Mac not reachable"
        case .connecting: return "Connecting…"
        case .reconnecting: return "Reconnecting…"
        case .live:
            if brainstorming { return "Brainstorming" }
            return muted ? "Muted" : speaking ? "Speaking" : "Listening"
        }
    }

    private var subtitle: String {
        if !reachable { return "Is Twingate, Tailscale or the same Wi-Fi on for this phone?" }
        guard let status else { return "Reaching your Mac…" }
        if phase == .off { return "Tap the mic to start talking" }
        if status.sessions.isEmpty { return "No session yet: /pointe:voice or pointe join on the Mac" }
        if status.mode == "session", let active = status.active { return "Focused on \(active)" + health }
        let needs = status.sessions.filter { $0.waiting || $0.needs != nil }.count
        let count = status.sessions.count
        return "Orchestrating \(count) session\(count == 1 ? "" : "s")" + (needs > 0 ? " · \(needs) need\(needs == 1 ? "s" : "") you" : "") + health
    }

    /// The Mac's reasons come in lower case without a full stop.
    static func sentence(_ s: String) -> String {
        let t = s.trimmingCharacters(in: .whitespaces)
        guard let first = t.first else { return t }
        let body = first.uppercased() + t.dropFirst()
        return ".!?".contains(body.last!) ? body : body + "."
    }

    // MARK: meeting

    private func meetingScreen(_ meeting: API.Meeting) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                if let problem = problem ?? call.problem {
                    Label(problem, systemImage: "exclamationmark.triangle.fill").font(.footnote).foregroundStyle(Brand.orange)
                }
                NotesFeed(notes: feed.notes, transcript: feed.transcript, speakers: meeting.speakers ?? [], filter: $noteFilter,
                          lookUp: { note in Task { await act { try await call.api.lookUp(note) } } },
                          setState: { note, state in
                              feed.setState(note.id, state)
                              Task { await act { try await call.api.setNote(note.id, state: state) } }
                          },
                          accept: { note in
                              feed.setState(note.id, "done")
                              Task { await act { try await call.api.setNote(note.id, accept: true) } }
                          },
                          thatWasMe: { turn in Task { await act { try await call.api.thatWasMe(turn.id) } } },
                          showTranscript: { Task { if demo == nil { await feed.loadTranscript(api: call.api) } } })
            }
            .padding(.horizontal, 16)
            .padding(.top, 10)
        }
        .scrollDismissesKeyboard(.interactively)
        .safeAreaInset(edge: .top, spacing: 0) {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    BrandHeader()
                    Spacer()
                    menu
                }
                MeetingBanner(meeting: meeting, setMode: setMeetingMode, speakers: { showSpeakers = true },
                              settings: { showMeetingSettings = true })
                if !reachable {  // the banner is the Mac's last word: say it may be stale
                    Label("Mac not reachable. The meeting goes on there; the notes catch up when it answers.",
                          systemImage: "wifi.exclamationmark")
                        .font(.footnote).foregroundStyle(Brand.orange)
                        .accessibilityIdentifier("meetingUnreachable")
                }
            }
            .padding(.horizontal, 18).padding(.top, 8).padding(.bottom, 10)
            .background(.bar)
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            VStack(spacing: 10) {
                if let hand = meeting.hand {
                    HandCard(hand: hand, participating: meeting.participating) { decision in
                        await act { try await call.api.hand(decision) }
                    }
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                }
                if let request = waiting.first {
                    RequestCard(session: request, showAgent: (status?.sessions ?? []).mixesAgents, answer: answer)
                }
                if typing {
                    TypeBar(prompt: "Ask Pointe, only you see it", send: { text in await act { try await call.api.ask(text) } }) { withAnimation(.snappy) { typing = false } }
                }
                MeetingBar(meeting: meeting, phase: phase, muted: muted, typing: typing, mic: micTapped,
                           toggleMode: { setMeetingMode(meeting.participating ? "listening" : "participating") },
                           ask: { withAnimation(.snappy) { typing.toggle() } }, speakers: { showSpeakers = true },
                           end: { confirmEnd = true })
            }
            .padding(.horizontal, 14).padding(.top, 8).padding(.bottom, 4)
            .background(alignment: .bottom) {  // notes scroll under the controls: fade them out instead of overlapping
                LinearGradient(stops: [.init(color: Brand.background.opacity(0), location: 0),
                                       .init(color: Brand.background.opacity(0.92), location: 0.25)],
                               startPoint: .top, endPoint: .bottom)
                    .ignoresSafeArea(edges: .bottom)
                    .allowsHitTesting(false)
            }
            .animation(.snappy, value: meeting.hand?.at)
        }
    }

    /// The end sheet, once per ended meeting, until you close it or discard the meeting.
    private var endSheetShown: Binding<Bool> {
        Binding(get: { meeting?.isEnded == true && meeting?.result != nil && closedEnd != (meetingSince ?? -1) },
                set: { if !$0 { closedEnd = meetingSince ?? -1 } })
    }

    private func openMeetingStart() {
        Task { if demo == nil { prefs = try? await call.api.prefs() } }
        showMeetingStart = true
    }

    private func setMeetingMode(_ mode: String) { Task { await act { try await call.api.meetingMode(mode) } } }

    private func meetingVendors() async -> (API.VendorsReply?, String?) {
        if demo != nil {
            let soniox = ProcessInfo.processInfo.arguments.contains("-noSoniox") ? "false" : "true"
            let json = #"{"vendors":{"room_audio":"soniox","notes":"anthropic","speech":"elevenlabs","commands":"anthropic"},"soniox":"# + soniox + "}"
            return (try? JSONDecoder().decode(API.VendorsReply.self, from: Data(json.utf8)), nil)
        }
        do {
            return (try await call.api.meetingVendors(), nil)
        } catch API.Failure.status(let code, _) where code == 404 || code == 405 || code == 400 {
            return (nil, "Pointe on the Mac is too old for meeting mode: update it there.")
        } catch API.Failure.status(_, let detail) {
            return (nil, Self.sentence(detail))
        } catch {
            return (nil, "The Mac did not answer. Is it reachable from this phone?")
        }
    }

    /// Nil when it started; otherwise the Mac's reason (no call, no Soniox key, one already on).
    private func startMeeting(_ mode: String, _ brief: String, _ sessions: [String], _ autoLookups: Bool) async -> String? {
        guard demo == nil else { return nil }
        do {
            try await call.api.startMeeting(mode: mode, brief: brief, sessions: sessions, autoLookups: autoLookups)
        } catch API.Failure.status(_, let detail) {
            if detail == "No call is up." { return "No call is up. Start one here with the mic, or on the Mac, then start the meeting." }
            return detail.isEmpty ? "The Mac refused." : Self.sentence(detail)
        } catch {
            return "The Mac did not answer."
        }
        status = try? await call.api.status()
        return nil
    }

    private func loadPrefs() async -> API.Prefs? {
        demo != nil ? try? JSONDecoder().decode(API.Prefs.self, from: Data("{}".utf8)) : try? await call.api.prefs()
    }

    private func savePrefs(_ change: [String: any Sendable]) async -> Bool {
        guard demo == nil else { return true }
        let ok = (try? await call.api.setPrefs(change)) != nil
        if ok { prefs = try? await call.api.prefs() }
        return ok
    }

    // MARK: actions

    private func micTapped() {
        if phase == .live { call.toggleMute() } else if phase == .off { Task { await call.start() } }
    }

    private func setBrainstorm(_ on: Bool) {
        brainstormWanted = on
        Task {
            await act { try await call.api.listen(on) }
            brainstormWanted = nil  // from here the Mac's word decides
        }
    }

    /// Talk to one session only: it becomes the active one, in session mode.
    private func focus(_ name: String) {
        Task {
            await act {
                try await call.api.switchTo(name)
                try await call.api.mode("session")
            }
        }
    }

    private func disconnect(_ name: String) { Task { await act { try await call.api.disconnect(name) } } }
    private func setMode(_ mode: String) { Task { await act { try await call.api.mode(mode) } } }
    private func setPolish(_ on: Bool) async { await act { try await call.api.polish(on) } }

    private func say(_ text: String) async -> Bool {
        await act { try await call.api.say(text) }
    }

    private func correct(_ turn: API.Turn, _ text: String) async -> Bool {
        await act { try await call.api.correct(turn, to: text) }
    }

    /// One call to the Mac, then a fresh status. False, with the reason shown, if the Mac refused.
    @discardableResult
    private func act(_ work: () async throws -> Void) async -> Bool {
        guard demo == nil else { return true }
        do {
            try await work()
            problem = nil
        } catch API.Failure.status(409, let detail) {
            problem = detail == "no call is up" || detail.hasPrefix("HTTP") ? "Start the call first." : Self.sentence(detail)
            return false
        } catch API.Failure.status(404, _) where meeting == nil {
            problem = "Pointe on the Mac does not know this yet: update it."
            return false
        } catch API.Failure.status(_, let detail) {
            problem = Self.sentence(detail)
            return false
        } catch {
            problem = "The Mac did not answer."
            return false
        }
        status = try? await call.api.status()
        return true
    }

    private func poll() async {
        while !Task.isCancelled {
            call.checkHealth()  // a call that went quiet is redialled, not left showing "Listening"
            do {
                let fresh = try await call.api.status()
                if fresh != status { status = fresh }
                reachable = true
            } catch {
                reachable = false
            }
            // Live words need a quick refresh while the call is up; idle, once a second is enough.
            try? await Task.sleep(nanoseconds: call.state == .live ? 400_000_000 : 1_000_000_000)
        }
    }

    /// Approving needs Face ID (or the passcode): the phone may be unlocked in someone else's hand. Denying never does.
    private func answer(_ s: API.Session, _ allow: Bool) async {
        if allow {
            let context = LAContext()
            do {
                guard try await context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: "Approve what \(s.name) wants to run")
                else { return }
            } catch { return }
        }
        await act { try await call.api.answer(s, allow: allow) }
    }
}

/// What the call is doing, in one glance.
struct StatusLine: View {
    let title: String
    let subtitle: String
    let phase: Call.State
    let muted: Bool
    let speaking: Bool

    private var tint: Color {
        switch phase {
        case .live: return muted ? .secondary : speaking ? Brand.orange : .green
        case .connecting, .reconnecting: return .yellow
        case .off: return .secondary
        }
    }

    var body: some View {
        HStack(spacing: 10) {
            Circle().fill(tint).frame(width: 9, height: 9)
                .shadow(color: tint.opacity(0.7), radius: phase == .live && !muted ? 5 : 0)
                .symbolEffect(.pulse, isActive: speaking)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline).contentTransition(.opacity)
                Text(subtitle).font(.subheadline).foregroundStyle(.secondary).lineLimit(2)
            }
        }
        .animation(.easeInOut(duration: 0.2), value: title)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("statusLine")
    }
}

struct RequestCard: View {
    let session: API.Session
    var showAgent = false
    let answer: (API.Session, Bool) async -> Void
    @State private var busy = false
    @State private var answered = 0

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 6) {
                Label { Text("\(session.name) needs approval") } icon: { Image(systemName: "hand.raised.fill").foregroundStyle(Brand.orange) }
                    .font(.headline)
                if showAgent { AgentBadge(session: session) }
            }
            if let what = parsed.what { Text(what).font(.subheadline).foregroundStyle(.secondary) }
            Text(parsed.exact)  // word for word: this is what Approve runs
                .font(.system(.footnote, design: .monospaced)).textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(12).background(.black.opacity(0.35), in: RoundedRectangle(cornerRadius: 10))
            Text(session.voice_can_approve == true ? "Say yes or no, or tap." : "Too complex to read out: check it, then tap.")
                .font(.caption).foregroundStyle(.secondary)
            HStack(spacing: 10) {
                Button { act(false) } label: { Text("Deny").frame(maxWidth: .infinity) }
                    .buttonStyle(.bordered).tint(.gray).controlSize(.large)
                Button { act(true) } label: { Label("Approve", systemImage: "faceid").frame(maxWidth: .infinity) }
                    .buttonStyle(.borderedProminent).tint(Brand.orange).controlSize(.large)
            }
            .disabled(busy)
        }
        .padding(16)
        .background(Brand.card, in: RoundedRectangle(cornerRadius: 20))
        .overlay(RoundedRectangle(cornerRadius: 20).stroke(Brand.orange.opacity(0.55)))
        .sensoryFeedback(.warning, trigger: session.request_id)
        .sensoryFeedback(.success, trigger: answered)
    }

    /// The daemon sends "Tool: description" and then the tool's input as JSON. A shell command is shown alone, exactly; any
    /// other input is shown whole.
    private var parsed: (what: String?, exact: String) {
        let raw = session.request ?? ""
        let lines = raw.split(separator: "\n", maxSplits: 1).map(String.init)
        guard lines.count == 2, let data = lines[1].data(using: .utf8),
              let input = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return (nil, raw) }
        if let command = input["command"] as? String { return (lines[0], command) }
        if let path = input["file_path"] as? String { return (lines[0], path) }
        return (lines[0], lines[1])
    }

    private func act(_ allow: Bool) {
        busy = true
        Task { await answer(session, allow); busy = false; answered += 1 }
    }
}
