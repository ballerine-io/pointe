import LocalAuthentication
import SwiftUI

/// The call: who you are talking to, what was said, what needs you, and the controls, with the mic at your thumb.
struct CallView: View {
    let pairing: Pairing
    let unpair: () -> Void
    @State private var call: Call
    @AppStorage(Theme.key) private var theme = Theme.fallback.rawValue
    @State private var status: API.Status?
    @State private var reach = Reach.ok
    @State private var problem: String?
    @State private var showSessions = false
    @State private var editing: API.Turn?
    @State private var typing = false
    @State private var atBottom = true
    @State private var unseen = false
    @State private var dumpWanted: Bool?  // a brain dump: shown at once on a tap, before the Mac confirms
    @State private var showDumpReview = false
    @State private var dumpReviewClosed: String?  // the review closed here: Review in the bar opens it again
    @State private var feed = MeetingFeed()
    @State private var noteFilter = NotesFeed.Filter.all
    @State private var showMeetingStart = false
    @State private var showMeetingSettings = false
    @State private var showVoiceLock = false
    @State private var showConflictSettings = false
    @State private var showAlerts = false
    @State private var showIgnored = false
    @State private var showSpeakers = false
    @State private var confirmEnd = false
    @State private var meetingSince: Double?  // the meeting on now, or the one that just ended (its status drops `since`)
    @State private var closedEnd: Double?     // the ended meeting whose sheet you closed: not shown again unless asked
    @State private var prefs: API.Prefs?
    @State private var showBriefing = false
    @State private var showBriefingSettings = false
    @State private var briefingSeen: Set<String> = []  // ready banners dismissed here, before the Mac's status says so
    @State private var demoSchedule = Demo.briefingsPage?.schedule
    @State private var showSheet = false
    @State private var showSettings = false
    @State private var showFollow = ShowFollow()
    @State private var sensors = DriveSensors()
    @State private var driveWanted: Bool?  // shown at once on a tap, before the Mac confirms
    @State private var challengeClosed: String?  // the ended challenge closed here: a new one shows again
    @State private var showDictionary = false
    @State private var learnedToasts = LearnedToasts()
    @State private var toast: [String]?
    @State private var demoDictionary = DemoDictionary()
    @State private var whisperFollow = WhisperFollow()
    @State private var machineFilter: String?   // a view only: sends nothing, changes no mode
    @State private var sessionsOn: MachineName? // "Sessions on devbox": the Sessions sheet, that machine first
    @State private var showMachines = false
    @State private var fingerScrolling = false
    @State private var stageHeight: CGFloat = 0
    @State private var topHeight: CGFloat = 0
    @State private var demoAnswered: Set<String> = []  // the demo's requests answered here: their card goes, as a Mac's would
    private let demo: Demo?

    init(pairing: Pairing, unpair: @escaping () -> Void, demo: Demo? = nil) {
        self.pairing = pairing
        self.unpair = unpair
        self.demo = demo
        _call = State(initialValue: Call(pairing: pairing))
        _status = State(initialValue: demo?.status)
        _showSessions = State(initialValue: demo?.screen == .sessions || demo?.screen == .machinesSessions)
        _editing = State(initialValue: demo?.screen == .edit ? demo?.status.talk?.last(where: \.mine) : nil)
        _typing = State(initialValue: demo?.screen == .typing)
        _showMeetingStart = State(initialValue: demo?.screen == .meetingStart)
        #if DEBUG
        // `-demo call -sheet voiceLock`: a sheet open at launch, for screenshots and UI tests.
        switch demo == nil ? nil : UserDefaults.standard.string(forKey: "sheet") {
        case "voiceLock": _showVoiceLock = State(initialValue: true)
        case "briefing": _showBriefing = State(initialValue: true)
        case "briefingSettings": _showBriefingSettings = State(initialValue: true)
        case "meetingSettings": _showMeetingSettings = State(initialValue: true)
        case "alerts": _showAlerts = State(initialValue: true)
        case "dictionary": _showDictionary = State(initialValue: true)
        case "machines": _showMachines = State(initialValue: true)
        case "conflictSettings": _showConflictSettings = State(initialValue: true)
        case "showSettings": _showSettings = State(initialValue: true)
        case "show": _showSheet = State(initialValue: true)
        case "ignored": _showIgnored = State(initialValue: true)
        case "speakers": _showSpeakers = State(initialValue: true)
        case "sessions": _showSessions = State(initialValue: true)
        default: break
        }
        #endif
    }

    /// Show while it says: the Mac sends it only once this phone turned it on; the setting is checked here too, so
    /// turning it off hides the card at once.
    private var showing: API.Showing? { status?.show_on_phone == true ? status?.showing : nil }

    /// What the screen shows: the demo fixture is always live.
    private var phase: Call.State { demo == nil ? call.state : .live }
    private var live: Bool { phase == .live || phase == .reconnecting }
    private var muted: Bool { demo == nil ? call.muted : demo?.screen == .muted }
    private var speaking: Bool { demo == nil ? call.botSpeaking : demo?.screen == .speaking }

    private var dumping: Bool { dumpWanted ?? (status?.dumping ?? false) }
    private var dump: API.BrainDump? { status?.brain_dump }
    private var driving: Bool { driveWanted ?? (status?.driving ?? false) }
    private var suggestingDrive: Bool {
        sensors.suggester.suggests(enabled: sensors.enabled, live: phase == .live, driving: driving,
                                   meeting: meeting?.isOn == true, now: Date())
    }
    private var hearing: String { status?.hearing ?? "" }

    private var meeting: API.Meeting? { status?.meeting }
    /// The raised hand's alert id (hand:<meeting id>:<n>): two hands are two hands even when raised in the same second.
    private var handId: String? {
        guard let hand = meeting?.hand else { return nil }
        return status?.attention?.first { $0.kind == "hand" }?.id ?? "at:\(hand.at ?? 0)"
    }

    /// Push to talk: this phone's press, at once; the Mac's gate only while the phone holds none (TalkGate.shows).
    private var talking: Bool { call.talk.ptt && call.talk.shows(macOpen: status?.ptt?.open == true) }
    private var ringTalk: RingTalk? {
        guard call.talk.ptt else { return nil }
        return RingTalk(talking: talking, style: call.talkStyle, press: { call.talkPress(.ring) }, release: { call.talkRelease(.ring) },
                        toggle: { call.talkToggle() })
    }

    var body: some View {
        Group {
            if let meeting, meeting.isOn {
                meetingScreen(meeting)
            } else if let c = challengeShown, c.on || !driving {  // an ended one waits until you stop driving
                ChallengePanel(challenge: c, problem: problem, end: { await challenge("end") }, close: { challengeClosed = c.id })
                    .padding(.horizontal, 14).padding(.vertical, 8)
                    .transition(.opacity.combined(with: .scale(scale: 0.98)))
                    .safeAreaInset(edge: .top, spacing: 0) { top }
                    .safeAreaInset(edge: .bottom, spacing: 0) { bottom }
            } else if dumping {
                BrainDumpPanel(dump: dump ?? API.BrainDump(id: "want", state: "dumping", since: nil, thoughts: []), hearing: hearing,
                               done: { setDump(false) }, discard: { Task { await dumpAction("discard") } }, problem: problem)
                    .padding(.horizontal, 14).padding(.vertical, 8)
                    .transition(.opacity.combined(with: .scale(scale: 0.98)))
                    .safeAreaInset(edge: .top, spacing: 0) { top }
                    .safeAreaInset(edge: .bottom, spacing: 0) { bottom }
            } else if driving {
                DriveScreen(status: status, speaking: speaking, stop: { setDrive(false) })
                    .transition(.opacity)
                    .safeAreaInset(edge: .top, spacing: 0) { top }
                    .safeAreaInset(edge: .bottom, spacing: 0) { bottom }
            } else {
                chat
            }
        }
        .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { stageHeight = $0 }  // less the keyboard, when it is up
        .animation(.smooth(duration: 0.3), value: dumping)
        .animation(.smooth(duration: 0.3), value: driving)
        .onChange(of: status?.drive) {
            call.driving = status?.driving ?? false
            if driving { typing = false }
            DriveNowPlaying.update(status: status, driving: status?.driving ?? false)
        }
        .animation(.smooth(duration: 0.3), value: challengeShown?.id)
        .onChange(of: dump?.inReview, initial: true) {  // the prompt arrived (or was there at launch): the review opens once per dump; Close keeps it away until Review
            if let dump, dump.inReview, dump.id != dumpReviewClosed { showDumpReview = true } else if dump?.inReview != true { showDumpReview = false }
        }
        .brandStage()
        .sheet(isPresented: $showDumpReview) {
            if let dump {
                BrainDumpReview(dump: dump, sessions: (status?.sessions ?? []).filter { $0.online != false }.map(\.name), active: status?.active,
                                problem: problem,
                                edit: { text in await dumpAction("edit", text: text) },
                                send: { to in
                                    switch to {
                                    case .orchestrator: await dumpAction("send", to: "orchestrator")
                                    case .session(let name): await dumpAction("send", session: name)
                                    }
                                },
                                more: { showDumpReview = false; await dumpAction("more") },
                                read: { await dumpAction("read") },
                                challenge: { showDumpReview = false; await challenge("start") },
                                discard: { showDumpReview = false; await dumpAction("discard") },
                                close: { dumpReviewClosed = dump.id; showDumpReview = false })
                    .presentationDetents([.large])
                    .presentationBackground(Brand.group)
            }
        }
        .sheet(isPresented: $showSessions) {
            SessionsSheet(status: status, switchTo: focus, disconnect: disconnect, setMode: setMode, filter: $machineFilter)
                .presentationDetents([.medium, .large])
                .presentationBackground(Brand.group)
        }
        .sheet(item: $sessionsOn) { on in
            SessionsSheet(status: status, switchTo: focus, disconnect: disconnect, setMode: setMode, section: on.id, filter: $machineFilter)
                .presentationDetents([.large])
                .presentationBackground(Brand.group)
        }
        .sheet(isPresented: $showMachines) {
            MachinesSheet(status: status, pairing: pairing, ownerCheck: ownerCheck, invite: makeInvite,
                          cancelInvite: cancelInvite, revoke: revokeMachine)
                .presentationDetents([.large])  // the code and its countdown must be on screen, on an SE too
                .presentationBackground(Brand.group)
        }
        .sheet(item: $editing) { turn in
            EditTurnSheet(turn: turn) { text in await correct(turn, text) }
                .presentationDetents([.medium])
                .presentationBackground(Brand.group)
        }
        .sheet(isPresented: $showMeetingStart) {
            MeetingStartSheet(sessions: status?.sessions ?? [], defaults: prefs, vendors: meetingVendors, start: startMeeting)
                .presentationBackground(Brand.group)
        }
        .sheet(isPresented: $showMeetingSettings) {
            MeetingSettingsSheet(load: loadPrefs, save: savePrefs).presentationDetents([.medium, .large])
                .presentationBackground(Brand.group)
        }
        .sheet(isPresented: $showVoiceLock) {
            if let lock = status?.voice_lock {
                VoiceLockSheet(lock: lock, callUp: phase == .live, pushToTalk: status?.ptt?.mode == "ptt", send: voiceprint, ownerCheck: ownerCheck)
                    .presentationDetents([.medium, .large])
                    .presentationBackground(Brand.group)
            }
        }
        .sheet(isPresented: $showConflictSettings) {
            ConflictSettingsSheet(load: loadPrefs, save: savePrefs).presentationDetents([.medium, .large])
                .presentationBackground(Brand.group)
        }
        .sheet(isPresented: $showBriefing) {
            BriefingSheet(status: status?.briefing, callUp: phase == .live, meetingOn: meeting?.isOn == true,
                          load: loadBriefings, act: briefing)
                .presentationDetents([.medium, .large])
                .presentationBackground(Brand.group)
        }
        .sheet(isPresented: $showBriefingSettings) {
            BriefingSettingsSheet(load: { await loadBriefings()?.schedule }, save: saveBriefingSchedule)
                .presentationDetents([.medium, .large])
                .presentationBackground(Brand.group)
        }
        .sheet(isPresented: $showAlerts) {
            AlertsSheet(phone: AlertCenter.shared.enabled, watch: prefs?.watchApprove ?? false,
                        setPhone: { await AlertCenter.shared.setEnabled($0) }, setWatch: setWatchApprove)
                .presentationDetents([.medium, .large])
                .presentationBackground(Brand.group)
        }
        .sheet(isPresented: $showSheet) {
            ShowSheet(showing: showing, earlier: status?.show_on_phone == true ? status?.shown_earlier ?? [] : [],
                      follow: $showFollow, load: loadArtifact)
                .presentationBackground(Brand.group)
        }
        .sheet(isPresented: $showSettings) {
            ShowSettingsSheet(on: status?.show_on_phone == true, set: setShowOnPhone, ownerCheck: ownerCheck)
                .presentationDetents([.medium])
                .presentationBackground(Brand.group)
        }
        .onChange(of: showing?.id) { showFollow.follow(showing) }
        .sheet(isPresented: $showDictionary) {
            VocabularySheet(load: loadDictionary, change: changeDictionary, delete: deleteFromDictionary, setLearn: setLearn)
                .presentationDetents([.medium, .large])
                .presentationBackground(Brand.group)
        }
        .onChange(of: status?.dictionary) { showLearned(learnedToasts.fresh(status?.dictionary)) }
        .onChange(of: status?.whisper, initial: true) { if whisperFollow.follow(status?.whisper) { withAnimation(.snappy) { typing = true } } }
        .overlay(alignment: .bottom) {
            if let toast {
                LearnedToast(terms: toast) { undoLearned(toast) }
                    .padding(.bottom, 130)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.snappy, value: toast)
        .sheet(isPresented: $showIgnored) {
            if let ignored = status?.voice_lock?.ignored {
                IgnoredSheet(ignored: ignored).presentationDetents([.medium, .large]).presentationBackground(Brand.group)
            }
        }
        .sheet(isPresented: $showSpeakers) {
            SpeakersSheet(speakers: meeting?.speakers ?? []) { label, name in
                await act { try await call.api.nameSpeaker(label, name) }
            }
            .presentationDetents([.medium])
            .presentationBackground(Brand.group)
        }
        .sheet(isPresented: endSheetShown) {
            if let result = meeting?.result {
                MeetingEndSheet(result: result, notes: feed.notes, sessions: status?.sessions ?? [],
                                transcript: { (try? await call.api.transcript()) ?? [] },
                                save: { with in demo != nil ? "~/.claude-voice/meetings/demo.md" : (try? await call.api.exportMeeting(transcript: with)) ?? "" },
                                send: { to in await act { try await call.api.sendActions(to: to) } ? nil : problem ?? "" },
                                discard: { await act { try await call.api.discardMeeting() } })
                    .presentationBackground(Brand.group)
            }
        }
        .confirmationDialog("End the meeting? Pointe stops listening and writes the summary.", isPresented: $confirmEnd,
                            titleVisibility: .visible) {
            Button("End meeting", role: .destructive) { Task { await act { _ = try await call.api.endMeeting() } } }
                .accessibilityIdentifier("confirmEndMeeting")
        }
        .sensoryFeedback(.warning, trigger: handId) { _, new in new != nil }
        .onChange(of: meeting?.owner_known) { _, known in if known == true, problem == Self.reconnecting { problem = nil } }
        .onChange(of: "\(meeting?.since ?? 0)|\(status?.notes?.version ?? -1)|\(meeting?.isEnded == true)|\(noteFilter == .transcript ? meeting?.turns ?? 0 : 0)") {
            if let since = meeting?.since { meetingSince = since }
            guard demo == nil else { return }
            Task {
                await feed.sync(status, api: call.api)
                if noteFilter == .transcript { await feed.loadTranscript(api: call.api) }  // new turns, while you read them
            }
        }
        .task {
            if let demo {
                feed.useDemo(demo.notes); call.follow(demo.status.ptt)
                if demo.screen == .dictionaryLearned { toast = demo.status.dictionary?.learned_this_call?.map(\.term) }
                return
            }
            prefs = try? await call.api.prefs()
            if let prefs { call.setMicrophone(prefs.microphone) }
        }
        .task { if demo == nil { await poll() } }
        .task { if demo == nil { sensors.start() } }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active, demo == nil { Task { await call.resume() } }  // back from the background: redial if it dropped
            if phase == .background, demo == nil {  // leaving the screen: what waits now goes to the lock screen and the watch
                Task { await AlertCenter.shared.sync(status?.attention, api: call.api, machines: machines); AlertCenter.schedule() }
            }
        }
    }

    // MARK: pieces

    /// Pinned to the newest line while you are at the bottom; left alone, with a "New" pill, once you scroll up to read.
    private var chat: some View {
        ScrollViewReader { scroller in
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    ConversationView(turns: status?.talk ?? [], polish: status?.polish ?? false, hearing: hearing,
                                     draft: TalkDraft.line(draft: status?.ptt?.draft, open: call.talk.isOpen || status?.ptt?.open == true),
                                     large: status?.whisper?.on == true && status?.whisper?.held == nil,
                                     placeholder: !panelShown) { editing = $0 }
                    if !panelShown, let problem = Self.shownProblem(screen: problem, call: call.problem, mac: status?.problem) {
                        Label(problem, systemImage: "exclamationmark.triangle.fill")
                            .font(.brand(.footnote)).foregroundStyle(Brand.accent).padding(.bottom, 8)
                    }
                    Color.clear.frame(height: 1).id("end")
                }
                .padding(.horizontal, 16)
                .padding(.top, 10)
            }
            .overlay {  // the empty stage: Connect in the middle, where the conversation will be
                if panelShown { ConnectPanel(title: title, face: face, tap: connectTap).transition(.opacity) }
            }
            .animation(.easeInOut(duration: 0.2), value: panelShown)
            .scrollDismissesKeyboard(.interactively)
            .accessibilityIdentifier("conversation")
            .holdToTalk(call.talk.ptt && phase == .live, style: call.talkStyle, press: { call.talkPress(.caption) },
                        release: { call.talkRelease(.caption) }, toggle: { call.talkToggle() })
            .defaultScrollAnchor(.bottom, for: .initialOffset)  // only where it starts: growing content must not pull you down
            .defaultScrollAnchor(.top, for: .sizeChanges)
            .onScrollGeometryChange(for: ScrollPin.self) { geo in
                // What shows above the controls: the bounds reach under the dock, so its inset comes off first.
                ScrollPin(bottom: geo.bounds.maxY - geo.contentInsets.bottom >= geo.contentSize.height - 48,
                          room: geo.bounds.height - geo.contentInsets.bottom - geo.contentInsets.top)
            } action: { _, new in
                // Only your own finger takes the view off the newest line. When the keyboard, the type bar or a card takes
                // room (or gives it back), the view goes back to the end, so nothing new hides behind the controls.
                if new.bottom {
                    atBottom = true
                    unseen = false
                } else if fingerScrolling {
                    atBottom = false
                } else if atBottom {
                    Task { @MainActor in scroller.scrollTo("end", anchor: .bottom) }
                }
            }
            .onScrollPhaseChange { _, phase in fingerScrolling = phase == .tracking || phase == .interacting || phase == .decelerating }
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
                        Label("New", systemImage: "arrow.down").font(.brand(.subheadline, .semibold))
                            .padding(.horizontal, 14).padding(.vertical, 8)
                            .background(Brand.raised, in: Capsule())
                            .overlay(Capsule().stroke(Brand.orangeLine))
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
                BrandHeader(mac: status?.version)
                Spacer()
                if demo?.tried == true { DemoBadge { call.hangUp(); unpair() } }
                if status?.drive != nil {  // a mode, like a meeting: switched here, so the mic below never moves
                    Button { setDrive(!driving) } label: {
                        Image(systemName: driving ? "car.fill" : "car").font(.brand(.subheadline, .semibold))
                            .foregroundStyle(driving ? Brand.accent : .primary)
                            .frame(width: 36, height: 36)
                            .background(driving ? AnyShapeStyle(Brand.tint) : AnyShapeStyle(Brand.raised), in: Circle())
                            .touchTarget(width: 36, height: 36)
                    }
                    .buttonStyle(.plain)
                    .disabled(phase != .live && !driving)
                    .accessibilityLabel(DriveCopy.button)
                    .accessibilityIdentifier("driveButton")
                    .accessibilityValue(driving ? "On" : "Off")
                }
                Button { openMeetingStart() } label: {
                    Image(systemName: "person.3.fill").font(.brand(.subheadline, .semibold))
                        .frame(width: 36, height: 36).background(Brand.raised, in: Circle())
                        .touchTarget(width: 36, height: 36)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Start a meeting")
                .accessibilityIdentifier("startMeeting")
                menu
            }
            .dynamicTypeSize(...DynamicTypeSize.xxxLarge)  // chrome, like a navigation bar: the words below it take the room
            SessionChips(sessions: status?.sessions ?? [], known: status != nil, active: status?.active, mode: status?.mode,
                         focus: focus, orchestrate: { setMode("orchestrator") }, disconnect: disconnect,
                         showAll: { showSessions = true }, rename: rename, machines: machines, filter: $machineFilter,
                         showMachine: { sessionsOn = MachineName(id: $0) })
                .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
            if let showing {
                ShowCard(showing: showing) { showSheet = true }
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 3) {
                    // The empty stage says the same title and why in the middle of the screen: once is enough.
                    if !panelShown { StatusLine(title: title, subtitle: subtitle, phase: phase, muted: muted, speaking: speaking) }
                    if let awake = API.KeepAwake.shown(status, live: phase == .live) {
                        Text(awake).font(.brand(.caption)).foregroundStyle(Brand.dim).lineLimit(1)
                            .padding(.leading, 18)  // under the title, past the state dot
                            .accessibilityIdentifier("keepAwake")
                    }
                    if let n = status?.voice_lock?.ignored?.count, n > 0 {  // its own line: beside the state it wrapped the line above
                        Button { showIgnored = true } label: {
                            Text(VoiceLockCopy.ignored(n)).font(.brand(.caption)).foregroundStyle(Brand.muted).underline(color: Brand.lineStrong)
                                .touchTarget(height: 16)
                        }
                        .buttonStyle(.plain)
                        .padding(.leading, 18)
                        .accessibilityIdentifier("voiceIgnored")
                    }
                }
                Spacer(minLength: 8)
                // Hang up is in the bar below while the call is up: one of each control on a screen.
                if !panelShown, !live { ConnectPill(phase: phase, face: face, tap: connectTap) }
            }
        }
        .padding(.horizontal, 18)
        .padding(.top, 8)
        .padding(.bottom, 10)
        .dynamicTypeSize(...DynamicTypeSize.accessibility2)  // the state line grows further than the chrome above it
        .background(Brand.bg)
        .overlay(alignment: .bottom) { Rectangle().fill(Brand.line).frame(height: 1) }
        .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { topHeight = $0 }
        .animation(.snappy, value: showing?.id)
    }

    /// What the controls under the call may take: the screen (less the keyboard) less the header, and a strip of the
    /// conversation. Past that the cards scroll inside the dock, so the header is never pushed off the top.
    private var dockLimit: CGFloat {
        let above: CGFloat = driving || dumping || challengeShown != nil ? 280 : 56  // a panel (drive, brain dump, challenge) needs more than a strip
        return stageHeight > 0 ? max(180, stageHeight - topHeight - above) : .infinity
    }

    private var menu: some View {
        Menu {
            Toggle(isOn: Binding(get: { status?.polish ?? false }, set: { on in Task { await setPolish(on) } })) {
                Label("Clean up my words", systemImage: "wand.and.sparkles")
            }
            if status?.whisper != nil {
                Toggle(isOn: Binding(get: { status?.whisper?.on == true }, set: { on in Task { await setWhisper(on) } })) {
                    Label(WhisperCopy.button, systemImage: "waveform.badge.minus")
                }
                .accessibilityIdentifier("whisperItem")
            }
            Button { showSessions = true } label: { Label("Sessions and mode", systemImage: "rectangle.stack") }
            if status?.machines != nil {
                Button { showMachines = true } label: { Label(MachinesCopy.title, systemImage: "desktopcomputer") }
                    .accessibilityIdentifier("machinesItem")
            }
            if meeting?.isOn != true {
                Button { openMeetingStart() } label: { Label("Start a meeting", systemImage: "person.3") }
            }
            if meeting?.isEnded == true {
                Button { closedEnd = nil } label: { Label("The meeting that ended", systemImage: "doc.text") }
                    .accessibilityIdentifier("reopenMeetingEnd")
            }
            Button { showBriefing = true } label: { Label(BriefingCopy.title, systemImage: "sun.horizon") }
            Button { showBriefingSettings = true } label: { Label(BriefingCopy.settingsItem, systemImage: "clock") }
            Button { Task { await challenge(challengeOn ? "end" : "start") } } label: {
                Label(challengeOn ? ChallengeCopy.end : ChallengeCopy.menuItem, systemImage: "figure.fencing")
            }
            .disabled(phase != .live || meeting?.isOn == true || dumping || driving)  // never both: driving wins
            .accessibilityIdentifier("menu.challenge")
            Button { showMeetingSettings = true } label: { Label("Meeting settings", systemImage: "gearshape") }
            Button { showAlerts = true } label: { Label(AlertCopy.section, systemImage: "bell.badge") }
            if status?.drive != nil {
                Toggle(isOn: Binding(get: { sensors.enabled }, set: { sensors.setEnabled($0) })) {
                    Label(DriveCopy.suggestSetting, systemImage: "car")
                }
                .accessibilityIdentifier("driveSuggestSetting")
            }
            if status?.dictionary != nil {
                Button { showDictionary = true } label: { Label(VocabularyCopy.menuItem, systemImage: "text.book.closed") }
                    .accessibilityIdentifier("dictionaryItem")
            }
            if status?.voice_lock != nil {
                Button { showVoiceLock = true } label: { Label(VoiceLockCopy.title, systemImage: "lock.shield") }
            }
            if status?.conflicts != nil {
                Button { showConflictSettings = true } label: { Label(ConflictCopy.settingsTitle, systemImage: "exclamationmark.triangle") }
            }
            if status?.show_on_phone != nil {
                Button { showSettings = true } label: { Label(ShowCopy.setting, systemImage: "doc.text.magnifyingglass") }
                    .accessibilityIdentifier("showSettingItem")
            }
            Picker(selection: Binding(get: { call.talk.mode }, set: { setMicrophone($0) })) {
                Text("Always on").tag("always")
                Text("Push to talk").tag("ptt")
            } label: { Label("Microphone", systemImage: "mic") }
                .pickerStyle(.menu)
                .accessibilityIdentifier("microphoneSetting")
            if call.talk.ptt {
                Picker(selection: Binding(get: { call.talkStyle }, set: { call.talkStyle = $0 })) {
                    ForEach(TalkStyle.allCases, id: \.self) { Text($0.label).tag($0) }
                } label: { Label("Talk button", systemImage: "hand.tap") }
                    .pickerStyle(.menu)
                    .accessibilityIdentifier("talkStyleSetting")
            }
            Picker(selection: Binding(get: { prefs?.patience ?? TurnsCopy.defaultLevel }, set: { setPatience($0) })) {
                ForEach(TurnsCopy.levels, id: \.value) { level in Text(level.label).tag(level.value) }
            } label: { Label(TurnsCopy.setting, systemImage: "hourglass") }
                .pickerStyle(.menu)
                .accessibilityIdentifier("patienceSetting")
            Picker(selection: $theme) {
                ForEach(Theme.allCases) { Text($0.label).tag($0.rawValue) }
            } label: { Label(Theme.setting, systemImage: "circle.lefthalf.filled") }
                .pickerStyle(.menu)
                .accessibilityIdentifier("appearanceSetting")
            if let line = status?.local?.short {
                Section { Label(line, systemImage: "desktopcomputer").accessibilityIdentifier("localMode") }  // read-only
            }
            Divider()
            if demo?.tried == true {
                Button(DemoBadge.exit, systemImage: "xmark.circle") { call.hangUp(); unpair() }
            } else {
                Button("Unpair this phone", systemImage: "iphone.slash", role: .destructive) { call.hangUp(); unpair() }
            }
        } label: {
            Image(systemName: "ellipsis").font(.brand(.body, .semibold))
                .frame(width: 36, height: 36).background(Brand.raised, in: Circle())
                .frame(width: 44, height: 44).contentShape(Rectangle())
        }
        .padding(-4)  // a menu takes touches in its own frame only: 44 points laid out, 36 drawn and counted
        .accessibilityLabel("Settings")
    }

    private var bottom: some View {
        Dock(limit: dockLimit) {
            // What needs you sits by your thumb, never scrolled away under the conversation.
            conflictCard(inMeeting: false)
            if let b = status?.briefing, b.isOn || b.building == true, !showBriefing {  // the sheet has the same controls
                BriefingNowBar(status: b, act: briefing).transition(.move(edge: .bottom).combined(with: .opacity))
            }
            if let ready = readyBriefing {
                BriefingReadyCard(alert: ready, hear: { _ = await briefing(["action": "start"]) },
                                  dismiss: { await dismissBriefing(ready) })
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
            if suggestingDrive {
                DriveSuggestion(accept: { setDrive(true) }, dismiss: { sensors.suggester.dismiss() })
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
            if driving, let request = waiting.first {
                DriveRequestCard(session: request, status: status, more: waiting.count - 1)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            } else if let request = waiting.first {
                RequestCard(session: request, who: machines.label(request), showAgent: (status?.sessions ?? []).mixesAgents, answer: answer)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                if voiceUnsure { unsureNote }
                if waiting.count > 1 {
                    Text("\(waiting.count - 1) more waiting").font(.brand(.caption)).foregroundStyle(Brand.muted)
                }
            }
            if let w = status?.whisper, w.on, w.held == nil, !driving {
                WhisperCard(status: w, suggestPushToTalk: whisperFollow.suggestsPushToTalk(w) && !call.talk.ptt,
                            pushToTalk: { setMicrophone("ptt") }, notNow: { whisperFollow.notNow() },
                            back: { Task { await setWhisper(false) } })
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        } bar: {
            if typing && !driving {
                TypeBar(send: say) { withAnimation(.snappy) { typing = false } }
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
            BottomBar(phase: phase, muted: muted, dump: dumping && dump == nil ? API.BrainDump(id: "want", state: "dumping", since: nil, thoughts: []) : dump,
                      typing: typing, mic: micTapped, listen: dumpButton, type: { withAnimation(.snappy) { typing.toggle() } },
                      sessions: { showSessions = true }, hangUp: { call.hangUp() }, talk: ringTalk,
                      trace: call.talkTrace, driving: driving)
        }
        .padding(.horizontal, 14)
        .padding(.bottom, 4)
        .brandDock()
        .animation(.snappy, value: waiting.first?.request_id)
    }

    /// The newest disagreement between two sessions; the others wait behind it, counted.
    @ViewBuilder
    private func conflictCard(inMeeting: Bool) -> some View {
        let open = status?.conflicts ?? []
        if let newest = open.last {
            ConflictCard(conflict: newest, showAgents: (status?.sessions ?? []).mixesAgents, inMeeting: inMeeting,
                         live: phase == .live, act: { action, side in await conflictAct(newest.id, action, side) })
                .id(newest.id)
                .transition(.move(edge: .bottom).combined(with: .opacity))
            if open.count > 1 { Text(ConflictCopy.more(open.count - 1)).font(.brand(.caption)).foregroundStyle(Brand.muted) }
        }
    }

    /// Nil when the Mac took it; otherwise the reason, as the page words it.
    private func conflictAct(_ id: String, _ action: String, _ side: String?) async -> String? {
        if demo != nil {
            if action == "dismiss" { status?.conflicts?.removeAll { $0.id == id } }
            else if let side, let i = status?.conflicts?.firstIndex(where: { $0.id == id }) { status?.conflicts?[i].asked = (status?.conflicts?[i].asked ?? []) + [side] }
            return nil
        }
        do {
            try await call.api.conflict(id, action: action, side: side)
        } catch API.Failure.status(_, let detail) {
            return ConflictCopy.refusal(detail)
        } catch {
            return "The Mac did not answer."
        }
        await refreshStatus()
        return nil
    }

    /// Three yeses in a row the lock could not place: the tap still works, and re-enrolling may help.
    private var voiceUnsure: Bool { (status?.voice_lock?.unsure_streak ?? 0) >= 3 }
    private var unsureNote: some View {
        Text(VoiceLockCopy.unsure).font(.brand(.caption)).foregroundStyle(Brand.accent).accessibilityIdentifier("voiceUnsure")
    }

    /// An answerable request first: one whose machine is offline is back in its terminal.
    private var waiting: [API.Session] {
        (status?.sessions.filter { $0.waiting && $0.canApprove && !demoAnswered.contains($0.request_id ?? "") } ?? []).enumerated()
            .sorted { ($0.element.isOffline ? 1 : 0, $0.offset) < ($1.element.isOffline ? 1 : 0, $1.offset) }.map(\.element)
    }

    private var machines: MachineView { MachineView(status) }

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
        case .off: return ConnectCopy.offTitle(reach: reach, macOnACall: status?.connected == true)
        case .connecting: return ConnectCopy.connecting(macName)
        case .reconnecting: return "Reconnecting…"
        case .live:
            if challengeOn { return ChallengeCopy.state }
            if dumping { return BrainDumpCopy.state }
            if status?.hold != nil { return TurnsCopy.holding }
            if call.talk.ptt {
                if talking { return call.talkStyle.talkingLine }
                if speaking { return "Speaking" }
                if let note = call.talkNote { return note }
                if let why = call.talkClosedWhy { return TalkGate.closedLine(why, style: call.talkStyle) }
                return call.talk.roomHeard ? "Meeting: room is heard · \(call.talkStyle.label.lowercased())" : call.talkStyle.label
            }
            return muted ? "Muted" : speaking ? "Speaking" : "Listening"
        }
    }

    private var reachable: Bool { reach == .ok }

    /// The Mac's own name when its status says which machine is here; its address until then.
    private var macName: String { status?.machines?.first { $0.here == true }?.name ?? pairing.host }

    /// What Connect shows: the reason the last attempt failed, or what a tap does.
    private var face: ConnectFace {
        ConnectFace.make(phase: phase, reach: reach, host: call.place, problem: call.problem, macOnACall: status?.connected == true)
    }

    /// The empty stage: no call up here and nothing said yet. Its Connect is the only one on screen; the header's pill
    /// takes over once the conversation covers it.
    private var panelShown: Bool { phase != .live && (status?.talk ?? []).isEmpty && demo == nil }

    /// Connect, Try again, Cancel or Hang up: the one button, by state.
    private func connectTap() {
        if phase == .off { Task { await call.start() } } else { call.hangUp() }
    }

    private var subtitle: String {
        if reach == .rejected { return "Pair this phone again from the page." }
        if reach == .unreachable { return "Is Twingate, Tailscale or the same Wi-Fi on for this phone?" }
        guard let status else { return "Reaching your Mac…" }
        if phase == .off { return ConnectCopy.tapConnect }
        if status.sessions.isEmpty { return "No session yet: /pointe:voice or pointe join on the Mac" }
        if status.mode == "session", let active = status.active { return "Focused on \(active)" + health }
        let shown = machines.shown(machineFilter)  // the machine filter narrows this line too
        let needs = shown.filter { ($0.waiting || $0.needs != nil) && !$0.isOffline }.count
        let count = shown.count
        let on = machines.valid(machineFilter).map { " on \($0)" } ?? ""
        return "Orchestrating \(count) session\(count == 1 ? "" : "s")\(on)" + (needs > 0 ? " · \(needs) need\(needs == 1 ? "s" : "") you" : "") + health
    }

    /// This screen's own problem first, then the call's, then the Mac's (a refused key, a vendor down), as the page does.
    static func shownProblem(screen: String?, call: String?, mac: String?) -> String? {
        [screen, call, mac].compactMap { $0 }.first { !$0.isEmpty }
    }

    /// The Mac's reasons come in lower case without a full stop.
    static func sentence(_ s: String) -> String {
        let t = s.trimmingCharacters(in: .whitespaces)
        guard let first = t.first else { return t }
        let body = first.uppercased() + t.dropFirst()
        return ".!?".contains(body.last!) ? body : body + "."
    }

    /// The Mac's refusals of a meeting action, as sentences for the person holding the phone.
    static func refusal(_ code: Int, _ detail: String) -> String {
        switch detail {
        case "the meeting is already ending": return "The meeting is already ending: the summary is being written."
        case "end the meeting first": return "End the meeting first: it is still on."
        case "no meeting is on": return "No meeting is on."
        case "no meeting to act on": return "That meeting is gone: there is nothing to export or send."
        case "no session has that name": return "That session is no longer connected. Pick another one."
        case "name a session, and the meeting needs action items": return "Pick a session. Only a meeting with action items can send them."
        default: break
        }
        guard code == 400, !detail.isEmpty else { return sentence(detail) }
        let said = sentence(detail)
        return "Pointe on the Mac did not accept that: \(said.prefix(1).lowercased())\(said.dropFirst()) Update the app or Pointe on the Mac."
    }

    // MARK: meeting

    private func meetingScreen(_ meeting: API.Meeting) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                if let problem = Self.shownProblem(screen: problem, call: call.problem, mac: status?.problem) {
                    Label(problem, systemImage: "exclamationmark.triangle.fill").font(.brand(.footnote)).foregroundStyle(Brand.accent)
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
                    BrandHeader(mac: status?.version)
                    Spacer()
                    if phase == .live { hangUpIcon } else { ConnectPill(phase: phase, face: face, tap: connectTap) }
                    menu
                }
                .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
                MeetingBanner(meeting: meeting, setMode: setMeetingMode, speakers: { showSpeakers = true },
                              settings: { showMeetingSettings = true }, reconnect: reconnectAudio)
                if !reachable {  // the banner is the Mac's last word: say it may be stale
                    Label("Mac not reachable. The meeting goes on there; the notes catch up when it answers.",
                          systemImage: "wifi.exclamationmark")
                        .font(.brand(.footnote)).foregroundStyle(Brand.accent)
                        .accessibilityIdentifier("meetingUnreachable")
                }
            }
            .padding(.horizontal, 18).padding(.top, 8).padding(.bottom, 10)
            .background(Brand.bg)
            .overlay(alignment: .bottom) { Rectangle().fill(Brand.line).frame(height: 1) }
            .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { topHeight = $0 }
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            Dock(limit: dockLimit) {
                if let hand = meeting.hand {
                    HandCard(hand: hand, participating: meeting.participating) { decision in
                        await act { try await call.api.hand(decision) }
                    }
                    .id(handId)  // a new hand gets a new card: never the last one's busy buttons
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                }
                conflictCard(inMeeting: true)
                if let request = waiting.first {
                    RequestCard(session: request, who: machines.label(request), showAgent: (status?.sessions ?? []).mixesAgents, answer: answer)
                    if voiceUnsure { unsureNote }
                }
            } bar: {
                if typing {
                    TypeBar(prompt: "Ask Pointe, only you see it", send: { text in await act { try await call.api.ask(text) } }) { withAnimation(.snappy) { typing = false } }
                }
                MeetingBar(meeting: meeting, phase: phase, muted: muted, typing: typing, mic: micTapped,
                           toggleMode: { setMeetingMode(meeting.participating ? "listening" : "participating") },
                           ask: { withAnimation(.snappy) { typing.toggle() } }, speakers: { showSpeakers = true },
                           end: { confirmEnd = true }, talk: ringTalk)
            }
            .padding(.horizontal, 14).padding(.bottom, 4)
            .brandDock()
            .animation(.snappy, value: handId)
        }
    }

    /// The meeting's bar ends the meeting, not the call, so Hang up stays in the header: as an icon, like the menu beside
    /// it, so the name and the version keep their room.
    private var hangUpIcon: some View {
        Button(action: connectTap) {
            Image(systemName: "phone.down.fill").font(.brand(.subheadline, .semibold)).foregroundStyle(Brand.dangerText)
                .frame(width: 36, height: 36).background(Brand.raised, in: Circle())
                .touchTarget(width: 36, height: 36)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(ConnectCopy.hangUp)
        .accessibilityIdentifier("topConnect")
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

    static let reconnecting = "Reconnecting the room\u{2019}s audio. Speakers are labelled afresh: say \u{201C}Pointe, that\u{2019}s me\u{201D} again."

    /// The room's audio seems stuck: a new stream. Its speakers are labelled afresh, so the owner claims the seat again.
    private func reconnectAudio() {
        Task {
            if await act({ try await call.api.reconnectMeeting() }) {
                problem = Self.reconnecting
            }
        }
    }

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
            if detail == "No call is up." { return "No call is up. Start one here with Connect, or on the Mac, then start the meeting." }
            return detail.isEmpty ? "The Mac refused." : Self.refusal(409, detail)
        } catch {
            return "The Mac did not answer."
        }
        await refreshStatus()
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

    // MARK: challenge me

    private var challengeOn: Bool { status?.challenge?.on == true }

    /// On, or ended and not closed here; an ended one gives way to a brain dump, as on the page.
    private var challengeShown: API.ChallengeStatus? {
        guard let c = status?.challenge, ChallengeCopy.shown(c, dismissed: challengeClosed), c.on || !dumping else { return nil }
        return c
    }

    /// start or end. The Mac's refusal is shown as it gives it. The demo plays along on its own status.
    private func challenge(_ action: String) async {
        problem = nil
        if demo != nil {
            if action == "start" {
                status?.challenge = API.ChallengeStatus(id: "demo-\(Int(Date().timeIntervalSince1970))", on: true, since: nil, ended_at: nil,
                                                        plan: status?.brain_dump?.prompt?.text ?? status?.brain_dump?.thoughts.map(\.text).joined(separator: "\n") ?? "",
                                                        sessions: [], objections: 0,
                                                        verdict: nil, evidence: 0, items: [])
            } else {
                status?.challenge?.on = false
                status?.challenge?.ended_at = Date().timeIntervalSince1970
            }
            return
        }
        do {
            try await call.api.challenge(action)
        } catch API.Failure.status(_, let detail) {
            problem = Self.sentence(detail)
            return
        } catch {
            problem = "The Mac did not answer."
            return
        }
        await refreshStatus()
    }

    // MARK: audio briefings

    private var readyBriefing: API.Attention? {
        guard let alert = status?.briefingAlert, status?.briefing?.isOn != true, !briefingSeen.contains(alert.id) else { return nil }
        return alert
    }

    private func loadBriefings() async -> API.BriefingsPage? {
        if demo != nil { return Demo.briefingsPage }
        return try? await call.api.briefings()
    }

    /// Nil when the Mac took it; otherwise its reason. The demo plays along on its own status.
    private func briefing(_ body: [String: any Sendable]) async -> String? {
        let action = body["action"] as? String ?? ""
        if demo != nil {
            var b = status?.briefing ?? API.BriefingStatus(id: nil, latest_id: nil)
            switch action {
            case "start": (b.playing, b.paused, b.part, b.parts, b.ready) = (true, "", 1, 3, nil)
            case "skip": b.part = min((b.part ?? 1) + 1, b.parts ?? 1)
            case "continue": (b.playing, b.paused, b.part) = (true, "", min((b.part ?? 1) + 1, b.parts ?? 1))
            default: (b.playing, b.paused, b.part, b.parts) = (false, "", 0, 0)
            }
            status?.briefing = b
            return nil
        }
        do {
            try await call.api.briefing(body)
        } catch API.Failure.status(_, let detail) {
            return detail == "no call is up" ? BriefingCopy.cannotStart(callUp: false, meetingOn: false) : Self.sentence(detail)
        } catch {
            return "The Mac did not answer."
        }
        await refreshStatus()
        return nil
    }

    private func dismissBriefing(_ alert: API.Attention) async {
        briefingSeen.insert(alert.id)
        if demo == nil { await act { try await call.api.dismissAttention(alert.id) } }
    }

    private func saveBriefingSchedule(_ change: [String: any Sendable]) async -> Result<API.BriefingSchedule, BriefingNotSaved> {
        if demo != nil {
            guard var s = demoSchedule else { return .failure(BriefingNotSaved(message: BriefingCopy.notSaved(nil))) }
            if let t = change["time"] as? String { s.time = t }
            if let d = change["days"] as? [Int] { s.days = d }
            if let l = change["length"] as? String { s.length = l }
            if let v = change["speak_on_connect"] as? Bool { s.speak_on_connect = v }
            if let v = change["skip_empty"] as? Bool { s.skip_empty = v }
            demoSchedule = s
            return .success(s)  // no reminder in the demo: it would ask for notification permission mid-test
        }
        do {
            guard let fresh = try await call.api.setBriefingSchedule(change) else {
                return .failure(BriefingNotSaved(message: BriefingCopy.notSaved(nil)))
            }
            await BriefingReminder.apply(fresh)
            return .success(fresh)
        } catch API.Failure.status(_, let detail) {
            return .failure(BriefingNotSaved(message: BriefingCopy.notSaved(detail)))
        } catch {
            return .failure(BriefingNotSaved(message: BriefingCopy.notSaved(nil)))
        }
    }

    // MARK: voice lock

    /// Nil when the Mac took it; otherwise its reason (no call, a meeting on, no voiceprint yet).
    private func voiceprint(_ body: [String: any Sendable]) async -> String? {
        if demo != nil {
            if body["action"] as? String == "level" { status?.voice_lock?.level = body["level"] as? String }
            return nil
        }
        do {
            try await call.api.voiceprint(body)
        } catch API.Failure.status(_, let detail) {
            return Self.sentence(detail)
        } catch {
            return "The Mac did not answer."
        }
        await refreshStatus()
        return nil
    }

    /// Face ID or the passcode, as for Approve. Also in the demo: a lowering there must fail the same way.
    private func ownerCheck(_ reason: String) async -> Bool {
        (try? await LAContext().evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason)) == true
    }

    /// Turning it on lowers what an Approve needs, so it asks for Face ID first, like lowering the voice lock.
    private func setWatchApprove(_ on: Bool) async -> Bool {
        if on, !(await ownerCheck(AlertCopy.faceIDReason)) { return false }
        guard demo == nil else { return on }
        guard await savePrefs(["alerts.watch_approve": on]) else { return prefs?.watchApprove ?? false }
        return prefs?.watchApprove ?? on
    }

    // MARK: dictionary

    private func loadDictionary() async -> Result<API.DictionaryPage, VocabularyFailure> {
        if demo != nil { return .success(demoDictionary.page) }
        do { return .success(try await call.api.dictionary()) } catch { return .failure(.from(error)) }
    }

    private func changeDictionary(_ body: [String: any Sendable]) async -> Result<API.DictionaryPage, VocabularyFailure> {
        if demo != nil { return demoDictionary.apply(body) }
        do { return .success(try await call.api.changeDictionary(body)) } catch { return .failure(.from(error)) }
    }

    private func deleteFromDictionary(_ term: String) async -> Result<API.DictionaryPage, VocabularyFailure> {
        if demo != nil { return demoDictionary.delete(term) }
        do { return .success(try await call.api.deleteFromDictionary(term)) } catch { return .failure(.from(error)) }
    }

    private func setLearn(_ on: Bool) async -> Bool {
        if demo != nil {
            let p = demoDictionary.page
            demoDictionary.page = API.DictionaryPage(entries: p.entries, suggestions: on ? p.suggestions : [], ignored: p.ignored,
                                                     count: p.count, cap: p.cap, full: p.full, learn: on, problem: nil)
            return true
        }
        return await savePrefs(["dictionary.learn": on])
    }

    private func showLearned(_ terms: [String]) {
        guard !terms.isEmpty else { return }
        toast = terms
        Task {
            try? await Task.sleep(for: .seconds(8))
            if toast == terms { toast = nil }
        }
    }

    /// Undo: the learned terms come out of the dictionary again.
    private func undoLearned(_ terms: [String]) {
        toast = nil
        Task { for term in terms { _ = await deleteFromDictionary(term) } }
    }

    // MARK: show while it says

    private func loadArtifact(_ id: String) async -> Result<API.ArtifactView, ShowFailure> {
        if demo != nil { return Demo.artifact(id).map { .success($0) } ?? .failure(.gone) }
        do {
            return .success(try await call.api.artifact(id))
        } catch API.Failure.status(403, _) {
            return .failure(.off)
        } catch API.Failure.status(404, _) {
            return .failure(.gone)
        } catch {
            return .failure(.unreachable)
        }
    }

    /// Nil when the Mac took it; otherwise its reason.
    private func setShowOnPhone(_ on: Bool) async -> String? {
        if demo != nil { status?.show_on_phone = on; return nil }
        guard await savePrefs(["show.on_phone": on]) else { return "The Mac did not take the setting. Is Pointe on the Mac up to date?" }
        await refreshStatus()
        return nil
    }

    // MARK: actions

    private func setPatience(_ level: String) {
        Task { if !(await savePrefs(["turns.patience": level])) { problem = TurnsCopy.failed } }
    }

    private func setMicrophone(_ mode: String) {
        let before = call.talk.mode
        call.setMicrophone(mode)
        Task {
            guard !(await savePrefs(["microphone": mode])) else { return }
            call.setMicrophone(before)  // the Mac's gate is the rule: without it, the phone does not pretend
            problem = "The Mac did not take the microphone setting. Is Pointe on the Mac up to date?"
        }
    }

    /// The mic is a mic: it mutes a live call. Starting one is Connect's job (the ring reads disabled until then).
    private func micTapped() {
        if phase == .live && call.talk.ptt { return }  // the hold opens and closes it
        if phase == .live { call.toggleMute() }
    }

    /// Drive mode lives on the Mac. "I've stopped" leaves it: the request is then read out again normally, and the
    /// normal card (Face ID) answers what had to wait.
    private func setDrive(_ on: Bool) {
        if demo != nil { status?.drive?.on = on; return }
        driveWanted = on
        Task {
            do {
                try await call.api.drive(on)
                problem = nil
                await refreshStatus()
            } catch API.Failure.status(_, let detail) {
                problem = DriveCopy.refused(detail)
            } catch {
                problem = "The Mac did not answer."
            }
            driveWanted = nil  // from here the Mac's word decides
        }
    }

    // MARK: brain dump

    /// The bar's button: start, done, or open the review.
    private func dumpButton() {
        if let dump, dump.inReview { dumpReviewClosed = nil; showDumpReview = true; return }
        setDump(!dumping)
    }

    private func setDump(_ on: Bool) {
        dumpWanted = on
        Task {
            if demo != nil { demoDump(on ? "start" : "done") } else { await act { try await call.api.dump(on ? "start" : "done") } }
            dumpWanted = nil  // from here the Mac's word decides
        }
    }

    /// edit, send, more, read, discard. The Mac's refusal is shown as it gives it. The demo plays along on its own status.
    private func dumpAction(_ action: String, text: String? = nil, session: String? = nil, to: String? = nil) async -> Bool {
        if demo != nil { demoDump(action, text: text, session: session); return true }
        return await act { try await call.api.dump(action, text: text, session: session, to: to) }
    }

    private func demoDump(_ action: String, text: String? = nil, session: String? = nil) {
        switch action {
        case "start": status?.brain_dump = API.BrainDump(id: "demo-\(Int(Date().timeIntervalSince1970))", state: "dumping", since: nil, thoughts: [])
        case "done":
            guard var d = status?.brain_dump else { return }
            d.state = "review"
            let thoughts = d.thoughts.map(\.text)
            d.prompt = API.DumpPrompt(goal: thoughts.first ?? "", context: Array(thoughts.dropFirst()), constraints: [], open_questions: [],
                                      text: (["Goal\n\(thoughts.first ?? "")"] + (thoughts.count > 1 ? [(["Context"] + thoughts.dropFirst().map { "- \($0)" }).joined(separator: "\n")] : [])).joined(separator: "\n\n"))
            status?.brain_dump = d
        case "more": status?.brain_dump?.state = "dumping"
        case "edit": if let text { status?.brain_dump?.prompt?.text = text }
        case "send", "discard": status?.brain_dump = nil
        default: break
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

    // MARK: machines

    private func makeInvite() async -> Result<API.Invite, MachinesFailure> {
        if demo != nil { return .success(Demo.demoInvite) }
        do { return .success(try await call.api.invite()) } catch { return .failure(.from(error)) }
    }

    private func cancelInvite() async -> MachinesFailure? {
        if demo != nil { return nil }
        do { try await call.api.cancelInvite(); return nil } catch { return .from(error) }
    }

    private func revokeMachine(_ name: String) async -> MachinesFailure? {
        if demo != nil {
            status?.machines?.removeAll { $0.name == name }
            return nil
        }
        do {
            try await call.api.revoke(name)
            await refreshStatus()
            return nil
        } catch { return .from(error) }
    }

    private func rename(_ name: String, _ newName: String) {
        guard demo == nil else { return }
        Task {
            do {
                try await call.api.rename(name, to: newName)
                problem = nil
                await refreshStatus()
            } catch API.Failure.status(_, let detail) {
                problem = SessionsCopy.renameRefused(detail)
            } catch {
                problem = "The Mac did not answer."
            }
        }
    }
    private func setMode(_ mode: String) { Task { await act { try await call.api.mode(mode) } } }
    private func setPolish(_ on: Bool) async { await act { try await call.api.polish(on) } }

    /// Whisper mode is the Mac's setting, shared with the page; the demo flips its own copy.
    private func setWhisper(_ on: Bool) async {
        if demo != nil {
            let w = status?.whisper
            status?.whisper = API.WhisperStatus(on: on, output_gain: on ? 0.5 : 1, max_words: on ? 20 : nil,
                                                suggest_ptt: on && !call.talk.ptt, lock_note: on ? w?.lock_note : nil)
            return
        }
        if !(await savePrefs(["whisper": on])) { problem = WhisperCopy.failed }
    }

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
            problem = detail == "no call is up" || detail.hasPrefix("HTTP") ? "Start the call first." : Self.refusal(409, detail)
            return false
        } catch API.Failure.status(404, _) where meeting == nil {
            problem = "Pointe on the Mac does not know this yet: update it."
            return false
        } catch API.Failure.status(let code, let detail) {
            problem = Self.refusal(code, detail)
            return false
        } catch {
            problem = "The Mac did not answer."
            return false
        }
        await refreshStatus()
        return true
    }

    /// After an action: a failed fetch keeps the last good status, as poll() does. Setting nil blanked the Machines list
    /// (and every other list) until the next poll.
    private func refreshStatus() async {
        if let fresh = try? await call.api.status() { status = fresh }
    }

    private func poll() async {
        while !Task.isCancelled {
            call.checkHealth()  // a call that went quiet is redialled, not left showing "Listening"
            do {
                let fresh = try await call.api.status()
                if fresh != status { status = fresh }
                call.follow(fresh.ptt)
                await AlertCenter.shared.sync(fresh.attention, api: call.api, machines: MachineView(fresh))
                reach = .ok
            } catch API.Failure.status(let code, _) where code == 401 || code == 403 {
                reach = .rejected  // the Mac answers, and refuses this phone's key: not the same as the Mac being away
            } catch {
                reach = .unreachable
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
        if demo != nil { demoAnswered.insert(s.request_id ?? ""); return }
        await act { try await call.api.answer(s, allow: allow) }
    }
}

/// Where the conversation is scrolled to, and how much room it has.
struct ScrollPin: Equatable {
    let bottom: Bool
    let room: CGFloat
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
        case .live: return muted ? Brand.dim : speaking ? Brand.orange : Brand.success
        case .connecting, .reconnecting: return Brand.orange
        case .off: return Brand.dim
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {  // the dot belongs to the state: on its first line, however long
                Circle().fill(tint).frame(width: 8, height: 8)
                    .symbolEffect(.pulse, isActive: speaking)
                    .alignmentGuide(.firstTextBaseline) { $0[.bottom] + 3 }
                Text(title).font(.brand(.title3)).contentTransition(.opacity)
            }
            Text(subtitle).font(.brand(.subheadline)).foregroundStyle(Brand.muted).lineLimit(2)
                .padding(.leading, 18)
        }
        .animation(.easeInOut(duration: 0.2), value: title)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("statusLine")
    }
}

struct RequestCard: View {
    let session: API.Session
    /// "shop · devbox" when its machine needs saying.
    var who: String? = nil
    var showAgent = false
    let answer: (API.Session, Bool) async -> Void
    @State private var busy = false
    @State private var answered = 0

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 6) {
                Label { Text("\(who ?? session.name) needs approval") } icon: { Image(systemName: "hand.raised.fill").foregroundStyle(Brand.accent) }
                    .font(.brand(.headline))
                if showAgent { AgentBadge(session: session) }
            }
            if let what = parsed.what { Text(what).font(.brand(.subheadline)).foregroundStyle(Brand.muted) }
            FitScroll(limit: 150) {  // a long command scrolls in its box: Deny and Approve never leave the screen
                Text(parsed.exact)  // word for word: this is what Approve runs
                    .font(.system(.footnote, design: .monospaced)).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
            }
            .background(Brand.raised, in: RoundedRectangle(cornerRadius: 12))
            .accessibilityIdentifier("requestCommand")
            if session.isOffline {  // its machine dropped: the prompt is back in its terminal, and an answer would be stale
                Label(MachinesCopy.offlineCard, systemImage: "bolt.horizontal.circle")
                    .font(.brand(.subheadline)).foregroundStyle(Brand.muted)
                    .accessibilityIdentifier("requestOffline")
            } else {
                Text(session.voice_can_approve == true ? "Say yes or no, or tap." : "Too complex to read out: check it, then tap.")
                    .font(.brand(.caption)).foregroundStyle(Brand.muted)
                HStack(spacing: 10) {
                    Button { act(false) } label: { Text("Deny").frame(maxWidth: .infinity) }
                        .buttonStyle(.brandQuiet).controlSize(.large)
                    Button { act(true) } label: { Label("Approve", systemImage: "faceid").frame(maxWidth: .infinity) }
                        .buttonStyle(.brandPrimary).controlSize(.large)
                }
                .disabled(busy)
            }
        }
        .padding(16)
        .background(Brand.card, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.orangeLine))
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

/// A machine's name, as a sheet item.
struct MachineName: Identifiable, Equatable { let id: String }
