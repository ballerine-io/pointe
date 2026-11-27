import LocalAuthentication
import PointeKit
import SwiftUI

/// The call: who you are talking to, what was said, what needs you, and the controls, with the mic at your thumb.
struct CallView: View {
    let link: DaemonLink
    let unpair: () -> Void
    /// "Pair again" on a connection problem: the scanner, keeping this pairing until a new one works. None on the Mac.
    private let pairAgain: (() -> Void)?
    /// The Mac app's shell (its menu bar item, bubble and shortcut), which holds the call and hears each status. The
    /// iPhone has none: this screen is the whole app there.
    private let shell: CallShell?
    @State private var call: Call
    @State private var status: API.Status?
    @State private var outbox = Outbox()  // typed lines on their way to the Mac
    @State private var reach = Reach.ok
    /// Why the phone can't get through to its Mac, from the last status poll; nil while it answers (ConnectionProblem).
    @State private var trouble: ConnectionProblem?
    @State private var helping: ConnectionProblem?  // "How to fix" open on this problem
    @State private var problem: String?
    @State private var showSessions = false
    @State private var editing: API.Turn?
    @State private var typing = false
    @State private var follow = ScrollFollow()  // following the newest line, or left where you read, with New
    @State private var dumpWanted: Bool?  // a brain dump: shown at once on a tap, before the Mac confirms
    @State private var showDumpReview = false
    @State private var dumpReviewClosed: String?  // the review closed here: Review in the bar opens it again
    @State private var feed = MeetingFeed()
    @State private var noteFilter = NotesFeed.Filter.all
    @State private var showMeetingStart = false
    @State private var showMeetingSettings = false
    @State private var showVoiceLock = false
    @State private var showApprovals = false
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
    @AppStorage(MuteChoice.key) private var muteStored = false  // this device's own choice (Mute.swift)
    @State private var demoSkipped = false  // a demo's "Speaking…" line, skipped (Skip.swift)
    @State private var machineFilter: String?   // a view only: sends nothing, changes no mode
    @State private var sessionsOn: MachineName? // "Sessions on devbox": the Sessions sheet, that machine first
    @State private var showMachines = false
    @State private var disclosures = DisclosureGate()  // the one-time line after a machine is added, until its OK
    /// A machine invite that opened the app (pointe://machine?…): Add a machine opens on it, and sends nothing by itself.
    private var incoming: Binding<String?>
    @State private var showAgents = false      // Settings → Agents (Agents.swift)
    @State private var showPeople = false      // `-sheet people`: the People sheet by itself, for screenshots and UI tests
    @State private var showAddMachine = false  // `-sheet addMachine`, likewise
    @State private var machinesNext = false    // a machine was added from a link: the Machines list opens once that sheet has closed
    @State private var showAbout = false
    @State private var showNewSession = false
    @State private var showAddSessions = false
    @State private var showNightShift = false
    @State private var showPhone = false
    @State private var wide = false  // a Mac window wide enough for the sessions column
    @State private var showCallSettings = false
    @State private var showQuick = false  // the iPhone's Quick settings sheet (QuickSettings.swift)
    @State private var settingsAfterQuick = false  // its "All settings" opens Settings once it has closed
    @State private var settingsNext: CallSettingsLink?  // a row's own sheet, opened once Settings has closed
    @State private var stageHeight: CGFloat = 0
    @State private var topHeight: CGFloat = 0
    @State private var demoAnswered: Set<String> = []  // the demo's requests answered here: their card goes, as a Mac's would
    private let demo: Demo?

    init(pairing: Pairing, unpair: @escaping () -> Void, pairAgain: (() -> Void)? = nil, demo: Demo? = nil,
         incoming: Binding<String?> = .constant(nil)) {
        self.init(link: DaemonLink(pairing), unpair: unpair, pairAgain: pairAgain, demo: demo, incoming: incoming)
    }

    /// `call`: one that already exists (the Mac app's, which outlives its window); otherwise this screen makes its own.
    init(link: DaemonLink, call: Call? = nil, shell: CallShell? = nil, unpair: @escaping () -> Void = {},
         pairAgain: (() -> Void)? = nil, demo: Demo? = nil, incoming: Binding<String?> = .constant(nil)) {
        self.incoming = incoming
        self.link = link
        self.shell = shell
        self.unpair = unpair
        self.pairAgain = pairAgain
        self.demo = demo
        _call = State(initialValue: call ?? Call(link: link))
        _status = State(initialValue: demo?.status)
        _showSessions = State(initialValue: demo?.screen == .sessions || demo?.screen == .machinesSessions || demo?.screen == .newSession)
        _editing = State(initialValue: demo?.screen == .edit ? demo?.status.talk?.last(where: \.mine) : nil)
        _typing = State(initialValue: demo?.screen == .typing)
        _showMeetingStart = State(initialValue: demo?.screen == .meetingStart)
        _showNewSession = State(initialValue: demo?.screen == .peopleStart)
        _showNightShift = State(initialValue: demo?.screen == .nightShiftStart || demo?.screen == .nightShiftLedger)
        #if DEBUG
        // `-demo call -sheet voiceLock`: a sheet open at launch, for screenshots and UI tests.
        switch demo == nil ? nil : UserDefaults.standard.string(forKey: "sheet") {
        case "voiceLock": _showVoiceLock = State(initialValue: true)
        case "approvals": _showApprovals = State(initialValue: true)
        case "briefing": _showBriefing = State(initialValue: true)
        case "briefingSettings": _showBriefingSettings = State(initialValue: true)
        case "meetingSettings": _showMeetingSettings = State(initialValue: true)
        case "alerts": _showAlerts = State(initialValue: true)
        case "dictionary": _showDictionary = State(initialValue: true)
        case "machines": _showMachines = State(initialValue: true)
        case "people": _showPeople = State(initialValue: true)
        case "agents": _showAgents = State(initialValue: true)
        case "agentReply": AgentReplyOpener.shared.agent = AgentName(id: "hermes")  // as a tap on "hermes replied" does
        case "addMachine": _showAddMachine = State(initialValue: true)
        case "conflictSettings": _showConflictSettings = State(initialValue: true)
        case "showSettings": _showSettings = State(initialValue: true)
        case "show": _showSheet = State(initialValue: true)
        case "ignored": _showIgnored = State(initialValue: true)
        case "speakers": _showSpeakers = State(initialValue: true)
        case "sessions": _showSessions = State(initialValue: true)
        case "about": _showAbout = State(initialValue: true)
        case "settings": _showCallSettings = State(initialValue: true)
        case "quick": _showQuick = State(initialValue: true)
        default: break
        }
        #endif
    }

    /// Show while it says: the Mac sends it only once this phone turned it on; the setting is checked here too, so
    /// turning it off hides the card at once.
    /// On the Mac it shows whatever the setting says, as the page there does: the code is already on that screen's Mac.
    private var showsHere: Bool { Surface.isMac || status?.show_on_phone == true }
    private var showing: API.Showing? { showsHere ? status?.showing : nil }

    /// What the screen shows: the demo fixture is always live.
    private var phase: Call.State { demo == nil ? call.state : .live }
    private var live: Bool { phase == .live || phase == .reconnecting }
    private var muted: Bool { demo == nil ? call.muted : demo?.screen == .muted }
    private var speaking: Bool {
        demo == nil ? call.botSpeaking : demo?.screen == .speaking && !(demoSkipped || shell?.demoSkipped == true) && !MuteChoice.inEffect(status: status, stored: false)
    }

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
        return RingTalk(talking: talking, style: call.talkStyle, press: { call.talkPress(.ring, touched: $0) },
                        release: { call.talkRelease(.ring) }, toggle: { call.talkToggle(touched: $0) })
    }

    /// Settings and the demo's growing conversation sit outside `screen`: one more modifier on that chain and CI's compiler
    /// gave up type-checking it in reasonable time.
    var body: some View {
        framed
            .sheet(isPresented: $showCallSettings, onDismiss: openSettingsNext) { callSettingsSheet }
            #if os(iOS)
            .sheet(isPresented: $showQuick, onDismiss: {
                if settingsAfterQuick { settingsAfterQuick = false; showCallSettings = true }
            }) {
                QuickSheet(model: quickModel, set: setQuick, allSettings: { settingsAfterQuick = true })
                    .sheetSurface()
            }
            #endif
            .task { await growDemoTalk() }
            .sheet(isPresented: $showNewSession) {  // straight to the sheet, for a menu or a key (the Mac's New Session)
                NewSessionSheet(actions: starter, machine: demo?.screen == .peopleStart ? "avi-box" : nil).sheetSurface()
            }
            .sheet(isPresented: $showAddSessions) {  // the Mac's Add Sessions menu item
                AddSessionsSheet(actions: adder).sheetSurface()
            }
            .sheet(isPresented: $showNightShift) {
                NightShiftLedger(live: status?.night_shift, actions: nightShift, startOpen: demo?.screen == .nightShiftStart)
                    .presentationDetents([.large])
                    .sheetSurface()
            }
            .onChange(of: shell?.request) { _, request in if let request { perform(request.command) } }
            #if os(macOS)
            .sheet(isPresented: Binding(get: { helping != nil }, set: { if !$0 { helping = nil } })) {
                if let helping { ConnectionHelpSheet(problem: helping) { self.helping = nil } }
            }
            .sheet(isPresented: $showPhone) {
                PhoneSheet(phones: status?.phones?.paired ?? [], act: PhoneActions(api: call.api)).sheetSurface()
            }
            #endif
    }

    private var callSettingsSheet: some View {
        CallSettingsSheet(model: settingsModel, act: settingsActions).equatable()
            .presentationDetents([.large])
            .sheetSurface()
    }

    /// The long demo conversation grows, as a live one does.
    private func growDemoTalk() async {
        guard demo?.screen == .longTalk else { return }
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(1.5))
            status?.talk = (status?.talk ?? []) + [Demo.nextLine(after: status?.talk ?? [])]
        }
    }

    /// A wide Mac window has the page's left column: mode, sessions by machine, New session, recent requests. Narrow,
    /// and on the phone, the strip of sessions over the conversation and the Sessions sheet do that job.
    @ViewBuilder private var framed: some View {
        #if os(macOS)
        HStack(spacing: 0) {
            if wide {
                SessionsSheet(status: status, switchTo: focus, disconnect: disconnect, setMode: setMode, filter: $machineFilter, starter: starter, adder: adder,
                              docked: SessionsSheet.Docked(settings: { showCallSettings = true }, rename: rename),
                              share: share, removeMachine: removeTheirMachine)
                    .frame(width: 288)
                    .transition(.move(edge: .leading).combined(with: .opacity))
                Rectangle().fill(Brand.line).frame(width: 1).ignoresSafeArea()
            }
            screen
        }
        .background(Brand.bg.ignoresSafeArea())
        .onGeometryChange(for: Bool.self) { $0.size.width >= 780 } action: { now in withAnimation(.smooth(duration: 0.25)) { wide = now } }
        #else
        screen
        #endif
    }

    private var screen: some View {
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
        .motion(.smooth(duration: 0.3), value: dumping)
        .motion(.smooth(duration: 0.3), value: driving)
        .onChange(of: status?.drive) {
            call.driving = status?.driving ?? false
            if driving { typing = false }
            DriveNowPlaying.update(status: status, driving: status?.driving ?? false)
        }
        .motion(.smooth(duration: 0.3), value: challengeShown?.id)
        .onChange(of: dump?.inReview, initial: true) {  // the prompt arrived (or was there at launch): the review opens once per dump; Close keeps it away until Review
            if let dump, dump.inReview, dump.id != dumpReviewClosed { showDumpReview = true } else if dump?.inReview != true { showDumpReview = false }
        }
        .brandStage()
        .sheet(isPresented: $showDumpReview) {
            if let dump {
                BrainDumpReview(dump: dump, sessions: (status?.sessions ?? []).filter { $0.online != false && !machines.watchOnly($0) }.map(\.name), active: status?.active,
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
                    .sheetSurface()
            }
        }
        .sheet(isPresented: $showSessions) {
            SessionsSheet(status: status, switchTo: focus, disconnect: disconnect, setMode: setMode, filter: $machineFilter, starter: starter, adder: adder,
                          share: share, removeMachine: removeTheirMachine)
                .presentationDetents([.medium, .large])
                .sheetSurface()
        }
        .sheet(item: $sessionsOn) { on in
            SessionsSheet(status: status, switchTo: focus, disconnect: disconnect, setMode: setMode, section: on.id, filter: $machineFilter, starter: starter, adder: adder,
                          share: share, removeMachine: removeTheirMachine)
                .presentationDetents([.large])
                .sheetSurface()
        }
        .sheet(isPresented: $showMachines) {
            MachinesSheet(status: status, pairing: link.pairing, ownerCheck: ownerCheck, invite: makeInvite,
                          cancelInvite: cancelInvite, revoke: revokeMachine, adder: machineAdder, people: peopleActions,
                          disclosure: disclosures.pending(status), added: machineAdded, disclosureOK: disclosureOK)
                .presentationDetents([.large])  // the code and its countdown must be on screen, on an SE too
                .sheetSurface()
        }
        .background(machineSheets)
        .background(AgentReplyPresenter(load: agentReplies))
        .sheet(item: $editing) { turn in
            EditTurnSheet(turn: turn) { text in await correct(turn, text) }
                .presentationDetents([.medium])
                .sheetSurface()
        }
        .sheet(isPresented: $showMeetingStart) {
            MeetingStartSheet(sessions: status?.sessions ?? [], defaults: prefs, vendors: meetingVendors, start: startMeeting)
                .sheetSurface()
        }
        .sheet(isPresented: $showMeetingSettings) {
            MeetingSettingsSheet(load: loadPrefs, save: savePrefs).presentationDetents([.medium, .large])
                .sheetSurface()
        }
        .sheet(isPresented: $showVoiceLock) {
            if let lock = status?.voice_lock {
                VoiceLockSheet(lock: lock, callUp: phase == .live, pushToTalk: status?.ptt?.mode == "ptt", send: voiceprint, ownerCheck: ownerCheck)
                    .presentationDetents([.medium, .large])
                    .sheetSurface()
            }
        }
        .sheet(isPresented: $showConflictSettings) {
            ConflictSettingsSheet(load: loadPrefs, save: savePrefs).presentationDetents([.medium, .large])
                .sheetSurface()
        }
        .sheet(isPresented: $showBriefing) {
            BriefingSheet(status: status?.briefing, callUp: phase == .live, meetingOn: meeting?.isOn == true,
                          load: loadBriefings, act: briefing)
                .presentationDetents([.medium, .large])
                .sheetSurface()
        }
        .sheet(isPresented: $showBriefingSettings) {
            BriefingSettingsSheet(load: { await loadBriefings()?.schedule }, save: saveBriefingSchedule)
                .presentationDetents([.medium, .large])
                .sheetSurface()
        }
        .sheet(isPresented: $showAlerts) {
            AlertsSheet(phone: AlertCenter.shared.enabled, watch: prefs?.watchApprove ?? false,
                        setPhone: { await AlertCenter.shared.setEnabled($0) }, setWatch: setWatchApprove)
                .presentationDetents([.medium, .large])
                .sheetSurface()
        }
        .sheet(isPresented: $showSheet) {
            ShowSheet(showing: showing, earlier: showsHere ? status?.shown_earlier ?? [] : [],
                      follow: $showFollow, load: loadArtifact)
                .sheetSurface()
        }
        .sheet(isPresented: $showSettings) {
            ShowSettingsSheet(on: status?.show_on_phone == true, set: setShowOnPhone, ownerCheck: ownerCheck)
                .presentationDetents([.medium])
                .sheetSurface()
        }
        .onChange(of: showing?.id) { showFollow.follow(showing) }
        .sheet(isPresented: $showApprovals) {
            ApprovalsSheet(load: loadApprovals).sheetSurface()
        }
        .sheet(isPresented: $showAbout) {
            AboutSheet(mac: status?.version).presentationDetents([.medium]).sheetSurface()
        }
        .sheet(isPresented: $showDictionary) {
            VocabularySheet(load: loadDictionary, change: changeDictionary, delete: deleteFromDictionary, setLearn: setLearn)
                .presentationDetents([.medium, .large])
                .sheetSurface()
        }
        .onChange(of: status?.dictionary) { showLearned(learnedToasts.fresh(status?.dictionary)) }
        .onChange(of: status?.whisper, initial: true) { if whisperFollow.follow(status?.whisper) { withAnimation(.snappy) { typing = true } } }
        .sheet(isPresented: $showIgnored) {
            if let ignored = status?.voice_lock?.ignored {
                IgnoredSheet(ignored: ignored).presentationDetents([.medium, .large]).sheetSurface()
            }
        }
        .sheet(isPresented: $showSpeakers) {
            SpeakersSheet(speakers: meeting?.speakers ?? []) { label, name in
                await act { try await call.api.nameSpeaker(label, name) }
            }
            .presentationDetents([.medium])
            .sheetSurface()
        }
        .sheet(isPresented: endSheetShown) {
            if let result = meeting?.result {
                MeetingEndSheet(result: result, sendPending: meeting?.send_pending, sentTo: meeting?.sent_to,
                                notes: feed.notes, sessions: status?.sessions ?? [],
                                transcript: { (try? await call.api.transcript()) ?? [] },
                                save: { with in demo != nil ? "~/.claude-voice/meetings/demo.md" : (try? await call.api.exportMeeting(transcript: with)) ?? "" },
                                send: { to in await act { try await call.api.sendActions(to: to) } ? nil : problem ?? "" },
                                discard: { await act { try await call.api.discardMeeting() } })
                    .sheetSurface()
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
                prefs = await loadPrefs()  // the demo's Mac: Settings shows every switch
                return
            }
            #if DEBUG
            Task { await typeOnCue() }  // in this task, not a modifier of its own: the chain is at the type checker's limit
            #endif
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
          // The header above the conversation, not over it: laid over it (a top inset), the conversation's frame covered
          // the header and took VoiceOver's touches and hit tests there.
          VStack(spacing: 0) {
            top
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    ConversationView(turns: status?.talk ?? [], polish: status?.polish ?? false, hearing: hearing,
                                     draft: TalkDraft.line(draft: status?.ptt?.draft, open: call.talk.isOpen || status?.ptt?.open == true),
                                     large: status?.whisper?.on == true && status?.whisper?.held == nil,
                                     placeholder: !panelShown,
                                     outgoing: outbox.lines, retry: resend) { editing = $0 }
                    if !panelShown, let problem = Self.shownProblem(screen: problem, call: call.problem ?? echoNote, mac: status?.problem) {
                        Label(problem, systemImage: "exclamationmark.triangle.fill")
                            .font(.brand(.footnote)).foregroundStyle(Brand.accent).padding(.bottom, 8)
                    }
                    // The dock's fade reaches 16 points up over the conversation (brandDock): the newest line ends above it.
                    Color.clear.frame(height: 17).id("end")
                }
                .padding(.horizontal, 16)
                .padding(.top, 10)
            }
            .accessibilityIdentifier("conversation")  // before the overlay: after it, it covered the stage's own identifiers
            .overlay {  // the empty stage: Connect in the middle, where the conversation will be
                // In a scroll of its own: taller than the stage (large type, a long reason), it was drawn over the header.
                if panelShown { StageScroll { ConnectPanel(title: title, face: face, tap: connectTap, act: troubleAct) }.transition(.opacity) }
            }
            .motion(.easeInOut(duration: 0.2), value: panelShown)
            .scrollDismissesKeyboard(.interactively)
            .holdToTalk(call.talk.ptt && phase == .live, style: call.talkStyle, press: { call.talkPress(.caption) },
                        release: { call.talkRelease(.caption) }, toggle: { call.talkToggle() })
            .defaultScrollAnchor(.bottom, for: .initialOffset)  // only where it starts: growing content must not pull you down
            .defaultScrollAnchor(.top, for: .sizeChanges)
            .onScrollGeometryChange(for: ScrollPin.self) { ScrollPin($0) } action: { _, new in
                if follow.moved(bottom: new.bottom, offset: new.offset) {
                    Task { @MainActor in if follow.stillFollowing { scroller.scrollTo("end", anchor: .bottom) } }
                }
            }
            .onScrollPhaseChange { _, phase in
                follow.phase(scrolling: phase == .tracking || phase == .interacting || phase == .decelerating, animating: phase == .animating)
            }
            .onChange(of: "\(status?.talk?.last?.id ?? -1)|\(hearing)") {
                if follow.newLine() { withAnimation(.smooth(duration: 0.3)) { scroller.scrollTo("end", anchor: .bottom) } }
            }
            .overlay(alignment: .bottom) {
                if follow.pillShown {
                    Button {
                        follow.jumpToEnd()  // the pill goes at the tap, and lines arriving on the way are followed
                        withAnimation(.smooth) { scroller.scrollTo("end", anchor: .bottom) }
                    } label: {
                        Label("New", systemImage: "arrow.down").font(.brand(.subheadline, .semibold))
                            .padding(.horizontal, 14).padding(.vertical, 8)
                            .background(Brand.raised, in: Capsule())
                            .overlay(Capsule().stroke(Brand.orangeLine))
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("newLines")
                    .padding(.bottom, 8)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                }
            }
            .motion(.snappy, value: follow.pillShown)
            .safeAreaInset(edge: .bottom, spacing: 0) {
                // A dock that grows (a card, the switch, the type bar) covered the newest line: follow it while pinned.
                bottom.onGeometryChange(for: CGFloat.self) { $0.size.height } action: { _ in
                    if follow.stillFollowing { scroller.scrollTo("end", anchor: .bottom) }
                }
            }
          }
        }
    }

    private var top: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .center) {
                BrandHeader(mac: status?.version)
                Spacer()
                if demo?.tried == true { DemoBadge { call.hangUp(); unpair() } }
                #if os(iOS)  // drive mode is for a phone in a car: the Mac shows it and stops it, as the page does, and never starts it
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
                #endif
                #if os(iOS)  // first, as in the design; the Mac shows them as chips in its title strip
                QuickButton(offDefault: QuickRule.offDefault(quickModel)) { showQuick = true }
                #endif
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
            if !wide {  // the wide Mac window lists the sessions in its left column
            SessionChips(sessions: status?.sessions ?? [], known: status != nil, starting: status?.starting ?? [],
                         active: status?.active, mode: status?.mode,
                         focus: focus, orchestrate: { setMode("orchestrator") }, disconnect: disconnect,
                         showAll: { showSessions = true }, rename: rename, machines: machines, filter: $machineFilter,
                         showMachine: { sessionsOn = MachineName(id: $0) }, people: status?.people, share: share)
                .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
            }
            if let showing {
                ShowCard(showing: showing) { showSheet = true }
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 3) {
                    // The empty stage says the same title and why in the middle of the screen: once is enough.
                    if !panelShown {
                        StatusLine(title: title, subtitle: subtitle, phase: phase, muted: muted, speaking: speaking || title == MuteCopy.writing,
                                   broken: status?.key_refused != nil || status?.vendor_fault != nil, mute: muteControl, skip: skipControl)
                    }
                    #if os(iOS)  // the Mac keeps itself awake only for a call from another device: on the Mac there is nothing to say
                    if let awake = API.KeepAwake.shown(status, live: phase == .live) {
                        Text(awake).font(.brand(.caption)).foregroundStyle(Brand.dim).lineLimit(1)
                            .padding(.leading, 18)  // under the title, past the state dot
                            .accessibilityIdentifier("keepAwake")
                    }
                    #endif
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
        .motion(.snappy, value: showing?.id)
        .accessibilityElement(children: .contain)  // one container: the menu's platform button took the strip as its children
    }

    /// What the controls under the call may take: the screen (less the keyboard) less the header, and a strip of the
    /// conversation. Past that the cards scroll inside the dock, so the header is never pushed off the top.
    private var dockLimit: CGFloat {
        let above: CGFloat = driving || dumping || challengeShown != nil ? 280 : 56  // a panel (drive, brain dump, challenge) needs more than a strip
        return stageHeight > 0 ? max(180, stageHeight - topHeight - above) : .infinity
    }

    /// The ••• button: Settings, a sheet with every setting and screen of the call.
    private var menu: some View {
        Button { showCallSettings = true } label: {
            Image(systemName: "ellipsis").font(.brand(.body, .semibold))
                .frame(width: 36, height: 36).background(Brand.raised, in: Circle())
                .touchTarget(width: 36, height: 36)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Settings")
        .accessibilityIdentifier("settingsButton")
    }

    private var settingsModel: CallSettingsModel {
        CallSettingsModel(status: status, prefs: prefs, microphone: call.talk.mode, talkStyle: call.talkStyle, live: phase == .live,
                          dumping: dumping, driving: driving, driveSuggest: sensors.enabled, demo: demo?.tried == true,
                          outside: Self.outside(demo: demo != nil))
    }

    /// The iPhone's "Talk from outside the app"; a demo shows it on, and changes nothing.
    private static func outside(demo: Bool) -> Bool? {
        #if os(iOS)
        demo ? true : PhoneTalk.shared.outside
        #else
        nil
        #endif
    }

    private var settingsActions: CallSettingsActions {
        CallSettingsActions(setMicrophone: setMicrophone, setTalkStyle: { call.talkStyle = $0 }, setPatience: setPatience, setWaitCue: setWaitCue, setProgress: setProgress, setSessionTones: setSessionTones,
                            setNewSessionPermissions: setNewSessionPermissions,
                            setPolish: { on in Task { await setPolish(on) } }, setWhisper: { on in Task { await setWhisper(on) } },
                            setDriveSuggest: { sensors.setEnabled($0) },
                            setOutside: { on in
                                #if os(iOS)
                                if demo == nil { PhoneTalk.shared.outside = on }
                                #endif
                            },
                            open: { settingsNext = $0; showCallSettings = false },
                            challenge: { Task { await challenge(challengeOn ? "end" : "start") } },
                            unpair: { call.hangUp(); unpair() })
    }

    /// What the Mac's menus and keys ask of this screen.
    private func perform(_ command: ShellRequest.Command) {
        switch command {
        case .settings: showCallSettings = true
        case .sessions: showSessions = true
        case .newSession: showNewSession = true
        case .addSessions: showAddSessions = true
        case .brainDump: if phase == .live { dumpButton() }
        case .meeting: openMeetingStart()
        case .type: if !driving { withAnimation(.snappy) { typing = true } }
        case .about: showAbout = true
        case .briefing: showBriefing = true
        case .machines: showMachines = true
        case .phone: if demo == nil { showPhone = true }
        case .nightShift: showNightShift = true
        case .approve, .deny:  // the first card's buttons, from the Call menu: Approve asks for the owner as its button does
            guard let request = waiting.first, machines.mayAnswer(request), !driving else { return }
            Task { if let why = await answer(request, command == .approve) { problem = why } }
        }
    }

    private func openSettingsNext() {
        guard let next = settingsNext else { return }
        settingsNext = nil
        switch next {
        case .sessions: showSessions = true
        case .machines: showMachines = true
        case .meetingStart: openMeetingStart()
        case .meetingEnd: closedEnd = nil
        case .briefing: showBriefing = true
        case .briefingSettings: showBriefingSettings = true
        case .meetingSettings: showMeetingSettings = true
        case .alerts: showAlerts = true
        case .dictionary: showDictionary = true
        case .voiceLock: showVoiceLock = true
        case .approvals: showApprovals = true
        case .conflicts: showConflictSettings = true
        case .show: showSettings = true
        case .about: showAbout = true
        case .phone: showPhone = true
        case .nightShift: showNightShift = true
        case .agents: showAgents = true
        }
    }

    private var bottom: some View {
        Dock(limit: dockLimit, anchor: driving ? .top : .bottom) {  // driving, no card has a button: it reads from its top
            learnedToast
            if let held = status?.held, HeldCopy.badge(held) != nil, !driving {  // session mode: shown, never spoken
                HeldBadge(held: held, open: demo?.screen == .held, tell: { Task { await tellHeld() } })
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
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
            #if os(iOS)
            if suggestingDrive {
                DriveSuggestion(accept: { setDrive(true) }, dismiss: { sensors.suggester.dismiss() })
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
            #endif
            if let shift = status?.night_shift, shift.on, !showNightShift {  // the ledger has Stop too
                NightShiftStrip(shift: shift, open: { showNightShift = true }, stop: stopShift)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
            if let pending = status?.shift_pending, !driving {  // as a new session's read-back: on the road the spoken yes starts it
                ShiftCard(pending: pending, answer: answerShift)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
            if let pending = status?.start_pending, !driving {  // on the road nothing is tapped: the spoken yes starts it
                StartCard(pending: pending, answer: answerStart)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
            if let pending = status?.attach_pending, !driving {  // on the road the spoken yes or pick adds it
                AttachCard(pending: pending, answer: answerAttach)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
            if driving, let request = waiting.first {
                DriveRequestCard(session: request, status: status, more: waiting.count - 1)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            } else if let request = waiting.first {
                RequestCard(session: request, who: machines.label(request), showAgent: (status?.sessions ?? []).mixesAgents, turn: machines, answer: answer)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                if voiceUnsure { unsureNote }
                if waiting.count > 1 {
                    Text("\(waiting.count - 1) more waiting").font(.brand(.caption)).foregroundStyle(Brand.muted)
                }
            } else if let done = machines.lastResolved {
                // Somebody else answered it: one quiet line where the card was, for as long as the Mac says so.
                Label("\(machines.label(done.session)): \(done.line)", systemImage: done.session.resolved_by?.verdict == "deny" ? "xmark.circle" : "checkmark.circle")
                    .font(.brand(.footnote)).foregroundStyle(Brand.muted)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 6)
                    .transition(.opacity)
                    .accessibilityIdentifier("requestResolved")
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
            #if os(iOS)  // the Mac's microphone is a chip in its title strip (QuickRow)
            if !typing && !driving {
                MicModeSwitch(mode: call.talk.mode, style: call.talkStyle, set: setMicrophone)
            }
            #endif
            BottomBar(phase: phase, muted: muted, dump: dumping && dump == nil ? API.BrainDump(id: "want", state: "dumping", since: nil, thoughts: []) : dump,
                      typing: typing, mic: micTapped, listen: dumpButton, type: { withAnimation(.snappy) { typing.toggle() } },
                      sessions: { showSessions = true }, hangUp: { call.hangUp() }, talk: ringTalk,
                      trace: call.talkTrace, driving: driving)
            #if DEBUG
            NetTraceProbe(call: call)
            #endif
        }
        .padding(.horizontal, 14)
        .padding(.bottom, 4)
        .brandDock()
        .motion(.snappy, value: waiting.first?.request_id)
        .motion(.snappy, value: toast)
    }

    /// "Learned: …" with Undo, in the dock over the cards: laid over the screen at a fixed height it covered the mic-mode
    /// switch and the newest line's "edited".
    @ViewBuilder
    private var learnedToast: some View {
        if let toast {
            LearnedToast(terms: toast) { undoLearned(toast) }
                .transition(.move(edge: .bottom).combined(with: .opacity))
        }
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
        // never one this person may only watch: its prompt is its owner's to answer
        (status?.sessions.filter { $0.waiting && $0.canApprove && !machines.watchOnly($0) && !demoAnswered.contains($0.request_id ?? "") } ?? []).enumerated()
            .sorted { (rank($0.element), $0.offset) < (rank($1.element), $1.offset) }.map(\.element)
    }

    /// One this person may answer now, then one somebody else is asked first for, then one whose machine is offline.
    private func rank(_ s: API.Session) -> Int { s.isOffline ? 2 : machines.waitsFor(s) != nil ? 1 : 0 }

    private var machines: MachineView { MachineView(status) }

    @Environment(\.scenePhase) private var scenePhase

    /// The link to the Mac, from the call's own heartbeat: shown so "connected" is never a guess.
    private var health: String {
        guard phase == .live, demo == nil else { return "" }
        if call.quietSecs > 3 { return " · no answer for \(call.quietSecs) s" }
        return call.rttMs.map { " · \($0) ms" } ?? ""
    }

    private var title: String {
        CallTitle.line(phase: phase, reach: reach, status: status, call: call, macName: macName, dumping: dumping, talking: talking,
                       speaking: speaking, muted: muted)
    }

    private var reachable: Bool { reach == .ok }

    /// The Mac's own name when its status says which machine is here; its address until then.
    private var macName: String { status?.machines?.first { $0.here == true }?.name ?? link.host }

    /// What Connect shows: the reason the last attempt failed, or what a tap does.
    private var face: ConnectFace {
        ConnectFace.make(phase: phase, reach: reach, host: call.place, problem: call.problem, macOnACall: status?.connected == true,
                         trouble: trouble)
    }

    /// The empty stage: no call up here and nothing said yet. Its Connect is the only one on screen; the header's pill
    /// takes over once the conversation covers it.
    /// A connection problem takes the stage over an old conversation too: nothing can be said until it is fixed.
    private var panelShown: Bool { phase != .live && ((status?.talk ?? []).isEmpty || trouble != nil) && demo == nil }

    /// The problem card's buttons: Try again dials (and asks for the status at once), Pair again opens the scanner.
    private func troubleAct(_ action: ConnectionProblem.Action) {
        switch action {
        case .tryAgain: connectTap()
        case .pairAgain: pairAgain?()
        case .howToFix: helping = trouble
        }
    }

    /// Connect, Try again, Cancel or Hang up: the one button, by state.
    private func connectTap() {
        if phase == .off { Task { await call.start() } } else { call.hangUp() }
    }

    private var subtitle: String {
        if Surface.isMac, reach != .ok { return reach == .rejected ? MacCopy.keyRefused : MacCopy.daemonDown }
        if reach == .rejected { return "Pair this phone again from the page." }
        if reach == .unreachable { return "Is Twingate, Tailscale or the same Wi-Fi on for this phone?" }
        guard let status else { return Surface.isMac ? "Reaching Pointe on this Mac…" : "Reaching your Mac…" }
        if phase == .off { return ConnectCopy.tapConnectHere }
        if title == TurnsCopy.holding { return TurnsCopy.holdingHow }
        if status.sessions.isEmpty { return "No session yet: /pointe:voice or pointe join on the Mac" }
        if status.mode == "session", let active = status.active { return "Focused on \(active)" + health }
        let shown = machines.shown(machineFilter)  // the machine filter narrows this line too
        let needs = machines.needingYou(machineFilter)
        let count = shown.count
        let on = machines.machine(machineFilter).map { " on \($0)" } ?? (machines.valid(machineFilter) == nil ? "" : " of yours")
        return "Orchestrating \(count) session\(count == 1 ? "" : "s")\(on)" + (needs > 0 ? " · \(needs) need\(needs == 1 ? "s" : "") you" : "") + health
    }

    /// Why the device asks who is there. iOS shows the reason as its own sentence; macOS puts it after "Pointe is trying
    /// to", so there it starts in lower case.
    static func ownerReason(_ reason: String) -> String {
        Surface.isMac ? reason.prefix(1).lowercased() + reason.dropFirst() : reason
    }

    /// A Mac audio device whose voice processing would not start: the call is up, and the bot may hear itself.
    private var echoNote: String? { phase == .live && !call.cancelsEcho ? MacCopy.noEchoCancelling : nil }

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
                learnedToast
                if let hand = meeting.hand {
                    HandCard(hand: hand, participating: meeting.participating) { decision in
                        await act { try await call.api.hand(decision) }
                    }
                    .id(handId)  // a new hand gets a new card: never the last one's busy buttons
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                }
                conflictCard(inMeeting: true)
                if let request = waiting.first {
                    RequestCard(session: request, who: machines.label(request), showAgent: (status?.sessions ?? []).mixesAgents, turn: machines, answer: answer)
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
            .motion(.snappy, value: handId)
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
        // A demo's Mac has every setting: the waiting sound on and the progress updates off, as a new Mac has them.
        demo != nil ? try? JSONDecoder().decode(API.Prefs.self, from: Data(#"{"thinking.cue": true, "progress.spoken": false, "reports.tones": false, "sessions.permissions": "skip"}"#.utf8)) : try? await call.api.prefs()
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
        (try? await LAContext().evaluatePolicy(.deviceOwnerAuthentication, localizedReason: Self.ownerReason(reason))) == true
    }

    /// Turning it on lowers what an Approve needs, so it asks for Face ID first, like lowering the voice lock.
    private func setWatchApprove(_ on: Bool) async -> Bool {
        if on, !(await ownerCheck(AlertCopy.faceIDReasonHere)) { return false }
        guard demo == nil else { return on }
        guard await savePrefs(["alerts.watch_approve": on]) else { return prefs?.watchApprove ?? false }
        return prefs?.watchApprove ?? on
    }

    // MARK: dictionary

    /// The approvals record, from the Mac's journal; nil when it did not load.
    private func loadApprovals() async -> [API.Approval]? {
        if demo != nil { return Demo.approvals }
        return try? await call.api.approvals().approvals
    }

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
        Task {
            if demo != nil {
                if prefs == nil { prefs = await loadPrefs() }
                prefs?.patience = level
                return
            }
            if !(await savePrefs(["turns.patience": level])) { problem = TurnsCopy.failed }
        }
    }

    private func setWaitCue(_ on: Bool) {
        Task {
            if demo != nil { prefs?.waitCue = on; return }
            if !(await savePrefs(["thinking.cue": on])) { problem = ThinkingCopy.failed }
        }
    }

    private func setSessionTones(_ on: Bool) {
        Task {
            if demo != nil { prefs?.sessionTones = on; return }
            if !(await savePrefs(["reports.tones": on])) { problem = ThinkingCopy.failed }
        }
    }

    private func setNewSessionPermissions(_ value: String) {
        Task {
            if demo != nil { prefs?.newSessionPermissions = value; return }
            if !(await savePrefs(["sessions.permissions": value])) { problem = ThinkingCopy.failed }
        }
    }

    private func setProgress(_ on: Bool) {
        Task {
            if demo != nil { prefs?.progressSpoken = on; return }
            if !(await savePrefs(["progress.spoken": on])) { problem = ThinkingCopy.failed }
        }
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
        if demo != nil { status?.active = name; status?.mode = "session"; return }
        Task {
            await act {
                try await call.api.switchTo(name)
                try await call.api.mode("session")
            }
        }
    }

    private func disconnect(_ name: String) {
        if demo != nil { status?.sessions.removeAll { $0.name == name }; return }
        Task { await act { try await call.api.disconnect(name) } }
    }

    // MARK: new session (NewSession.swift)

    private var starter: NewSessionActions { NewSessionActions(ownerCheck: ownerCheck, options: startOptions, start: startSession) }

    private func startOptions(_ machine: String?) async throws -> NewSession.Options {
        if demo != nil, let options = Demo.startOptions(machine: machine, status: status) { return options }
        return try await call.api.startOptions(machine: machine)
    }

    /// The sheet's Start, after its Face ID. The demo plays along on its own status.
    private func startSession(_ draft: NewSession.Draft) async throws {
        if demo != nil {
            let folder = Demo.startOptions?.folders.first { $0.path == draft.folder }?.name ?? "shop"
            demoStarted(draft.body["name"] ?? folder, harness: draft.harness, machine: draft.machine)
            return
        }
        try await call.api.newSession(draft.body)
        await refreshStatus()
    }

    /// A tap on the read-back's card. Start needs Face ID (or the passcode), as Approve does; Cancel never does.
    private func answerStart(_ pending: NewSession.Pending, _ start: Bool) async {
        if start, !(await ownerCheck(NewSessionSheet.faceIDReason)) { return }
        if demo != nil {
            status?.start_pending = nil
            if start { demoStarted("shop-2", harness: "claude-code") }
            return
        }
        await act { try await call.api.newSession([start ? "confirm" : "cancel": pending.id]) }
    }

    // MARK: adding sessions (AddSessions.swift)

    private var adder: AddSessionsActions {
        AddSessionsActions(ownerCheck: ownerCheck, listing: addListing, join: joinSessions, reopen: { key in try await addSessions(["reopen": key]) })
    }

    private func joinSessions(_ keys: [String]) async throws {
        if demo != nil { return }
        try await call.api.joinSessions(keys)
        await refreshStatus()
    }

    private func addListing() async throws -> AddSessions.Listing {
        if demo != nil { return Demo.addListing }
        return try await call.api.addSessionsListing()
    }

    private func addSessions(_ body: [String: String]) async throws {
        if demo != nil { return }
        try await call.api.addSessions(body)
        await refreshStatus()
    }

    /// A tap on the read-back's card. Join needs Face ID (or the passcode), as Start does; Cancel never does.
    private func answerAttach(_ pending: AddSessions.Pending, _ yes: Bool, _ pick: String?) async {
        if yes, !(await ownerCheck(AddSessionsSheet.faceIDReason)) { return }
        if demo != nil {
            status?.attach_pending = nil
            return
        }
        var body = [yes ? "confirm" : "cancel": pending.id]
        if yes, let pick { body["pick"] = pick }  // one of the choices "which one?" read back
        await act { try await call.api.addSessions(body) }
    }

    /// The demo's start: a row under the sessions, then the session itself, as a Mac would show it.
    private func demoStarted(_ name: String, harness: String?, machine: String? = nil) {
        let label = Demo.startOptions?.harnesses.first { $0.name == harness }?.title
        let there = machine.flatMap { $0 == machines.here ? nil : $0 }
        let row = NewSession.Starting(id: "demo-\(name)", name: name, harness: harness, label: label, state: "starting", machine: there)
        status?.starting = (status?.starting ?? []) + [row]
        Task {
            try? await Task.sleep(for: .seconds(2))
            status?.starting?.removeAll { $0.id == row.id }
            status?.sessions.append(API.Session(name: name, working: false, waiting: false, request: nil, request_id: nil,
                                                voice_can_approve: nil, needs: nil, harness: harness, capabilities: nil, machine: there, online: true))
        }
    }

    // MARK: night shift (NightShift.swift)

    private var nightShift: NightShiftActions {
        NightShiftActions(ownerCheck: ownerCheck, load: loadShift, startOptions: { try await startOptions(nil) }, start: startShift, stop: stopShift)
    }

    private func loadShift(_ id: String?) async throws -> NightShift.Options {
        if demo != nil, let page = Demo.nightShiftPage(on: status?.night_shift?.on) { return page }
        return try await call.api.nightShift(id: id)
    }

    /// The sheet's Start, after its Face ID. The demo plays along on its own status.
    private func startShift(_ draft: NightShift.Draft) async throws {
        if demo != nil {
            status?.night_shift = Demo.runningShift
            return
        }
        try await call.api.startShift(draft)
        await refreshStatus()
    }

    /// Stop needs no one: after it Pointe sends nothing more, and a turn already running finishes on its own.
    private func stopShift() async {
        if demo != nil {
            status?.night_shift?.on = false
            return
        }
        await act { try await call.api.shiftAction("stop") }
    }

    /// A tap on the read-back's card. Start needs Face ID (or the passcode), as Approve does; Cancel never does.
    private func answerShift(_ pending: NightShift.Pending, _ start: Bool) async {
        if start, !(await ownerCheck(NightShiftSheet.faceIDReason)) { return }
        if demo != nil {
            status?.shift_pending = nil
            if start { status?.night_shift = Demo.runningShift }
            return
        }
        await act { try await call.api.shiftAction(start ? "confirm" : "cancel", id: pending.id) }
    }

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

    // MARK: people and machines (People.swift, AddMachine.swift)

    /// The sheets of people and machines, on a view of their own: the screen's chain of sheets is as long as the
    /// compiler takes.
    private var machineSheets: some View {
        Color.clear
        .sheet(isPresented: Binding(get: { incoming.wrappedValue != nil || showAddMachine },
                                    set: { if !$0 { incoming.wrappedValue = nil; showAddMachine = false } }),
               onDismiss: { if machinesNext { machinesNext = false; showMachines = true } }) {  // one sheet at a time
            // A machine invite that opened the app: the same sheet as Settings → Machines → Add a machine, with the line
            // in it. Added, the Machines list opens with the machine and what your voice sends where.
            AddMachineSheet(actions: machineAdder, line: incoming.wrappedValue ?? Self.launchLine, fromOutside: incoming.wrappedValue != nil) { machine in
                machineAdded(machine)
                machinesNext = true
            }
            .presentationDetents([.large])
            .sheetSurface()
        }
        .sheet(isPresented: $showPeople) {
            PeopleSheet(status: status, actions: peopleActions).presentationDetents([.large]).sheetSurface()
        }
        .sheet(isPresented: $showAgents) {
            AgentsSheet(actions: agentsActions, elsewhere: status?.agent_disclosure).presentationDetents([.large]).sheetSurface()
        }
        // Added from the page or a terminal: the same one line, here, when the Machines sheet is not the one showing it.
        .alert(disclosures.pending(status).map { PeopleCopy.added($0.machine, owner: MachineView(status).info($0.machine)?.owner) } ?? "",
               isPresented: Binding(get: { disclosures.pending(status) != nil && !showMachines && !machinesNext && incoming.wrappedValue == nil && !showAddMachine },
                                    set: { _ in }),
               presenting: disclosures.pending(status)) { d in
            Button(PeopleCopy.ok) { disclosureOK(d) }.accessibilityIdentifier("disclosureOK")
        } message: { d in Text(PeopleCopy.disclosure(d, owner: MachineView(status).info(d.machine)?.owner)) }
    }


    #if DEBUG
    /// `-demo people -sheet addMachine -machineLine <line>`: the line as if scanned, for UI tests (no camera there).
    private static var launchLine: String { UserDefaults.standard.string(forKey: "machineLine") ?? "" }
    #else
    private static let launchLine = ""
    #endif

    private var machineAdder: AddMachineActions {
        AddMachineActions(ownerCheck: ownerCheck, add: { line, name in
            if demo != nil {
                let (added, fresh) = try Demo.addMachine(line, name: name, status: status)
                status = fresh
                return added
            }
            let added = try await call.api.addMachine(line: line, name: name)
            await refreshStatus()
            return added
        })
    }

    private func machineAdded(_ machine: API.MachineAdded) { disclosures.machineAdded(machine) }

    private var agentsActions: AgentsActions {
        if demo != nil { return Demo.agentsActions(ownerCheck: ownerCheck) }
        let api = call.api
        return AgentsActions(ownerCheck: ownerCheck, load: { try await api.agents() },
                             add: { try await api.addAgent(kind: $0, name: $1, url: $2, secret: $3, agent: $4) },
                             remove: { try await api.removeAgent($0) },
                             seen: { name in try? await api.agentSeen(name) })
    }

    private var agentReplies: ((String) async throws -> API.AgentReplies)? {
        guard demo == nil else { return Demo.agentReplies }
        let api = call.api
        return { try await api.agentReplies($0) }
    }

    private func disclosureOK(_ d: API.Disclosure) {
        let machine = disclosures.dismiss(d)
        if demo != nil { status?.disclosure = nil; return }
        Task { try? await call.api.disclosureSeen(machine); await refreshStatus() }
    }

    private var peopleActions: PeopleActions {
        if demo != nil { return Demo.peopleActions(ownerCheck: ownerCheck, status: $status) }
        let api = call.api
        return PeopleActions(ownerCheck: ownerCheck, load: { try await api.people() },
                             invite: { try await api.invitePerson(name: $0, grant: $1) },
                             state: { try await api.personInviteState() }, cancel: { try await api.cancelPersonInvite() },
                             grant: { try await api.setGrant($0, $1) }, remove: { try await api.removePerson($0) },
                             settings: { try await api.peopleSettings() }, setSettings: { try await api.setPeopleSettings($0) })
    }

    /// A session's Private, or Shared with people. The lock shows at the tap; the Mac's next status confirms it.
    private func share(_ name: String, _ makePrivate: Bool) {
        if let i = status?.sessions.firstIndex(where: { $0.name == name }) { status?.sessions[i].private = makePrivate }
        guard demo == nil else { return }
        Task {
            do { try await call.api.share(name, private: makePrivate); problem = nil } catch { problem = PeopleCopy.refusal(error) }
            await refreshStatus()
        }
    }

    /// Remove under "avi-box removed you" in the Sessions list, after its confirm: Face ID, then the machine leaves
    /// this voice. Nil when it went.
    private func removeTheirMachine(_ name: String) async -> String? {
        guard await ownerCheck("Remove a machine: \(name)") else { return nil }
        return await revokeMachine(name)?.text
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
    private func setMode(_ mode: String) {
        if demo != nil { status?.mode = mode; return }
        Task { await act { try await call.api.mode(mode) } }
    }

    private func setPolish(_ on: Bool) async {
        if demo != nil { status?.polish = on; return }
        await act { try await call.api.polish(on) }
    }

    private var quickModel: QuickModel { QuickModel(status: status, microphone: call.talk.mode) }

    /// A quick setting from the iPhone's sheet: the demo changes its own copy; otherwise the Mac keeps it.
    private func setQuick(_ change: QuickChange) {
        if case .microphone(let mode) = change { setMicrophone(mode); return }
        change.apply(to: &status)
        guard demo == nil else { return }
        Task {
            if !(await savePrefs(change.prefs)) { problem = "The Mac did not take the setting. Is Pointe on the Mac up to date?" }
            await refreshStatus()
        }
    }

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

    /// The mute button beside the status line; nil on a Mac from before reading mode, which cannot stop its voice.
    private var muteControl: StatusLine.Mute? {
        guard status?.reading != nil || muteStored else { return nil }
        return StatusLine.Mute(on: MuteChoice.on(status: status, stored: muteStored), held: status?.reading?.held != nil) {
            Task { await setMute(!MuteChoice.on(status: status, stored: muteStored)) }
        }
    }

    /// Mute: this device keeps its choice, and the call (if one is up) takes it. Muted mid-sentence, what this device
    /// still holds to play stops now. The demo flips its own copy and keeps nothing.
    private func setMute(_ on: Bool) async {
        if demo != nil {
            if status?.reading != nil { status?.reading = API.ReadingStatus(on: on, writing: on && demo?.screen == .speaking) }
            return
        }
        muteStored = on
        if on, status?.reading?.held == nil { call.hush() }
        if !(await act { try await call.muteRequests.send(on, with: call.api) }) { problem = MuteCopy.failed }
    }

    /// The skip button beside the status line, only while Pointe's voice is heard.
    private var skipControl: (() -> Void)? {
        guard SkipRule.shows(speaking: speaking, muted: MuteChoice.inEffect(status: status, stored: muteStored)) else { return nil }
        return { Task { await skipNow() } }
    }

    /// Skip: what this device still holds to play stops now, and the Mac drops the line and goes on to the next one.
    /// The demo's line just ends.
    private func skipNow() async {
        if demo != nil { demoSkipped = true; shell?.demoSkipped = true; return }
        call.hush()
        if !(await act { try await call.api.skip() }) { problem = SkipCopy.failed }
    }

    /// The held news badge's Tell me: Pointe says what the other sessions said (the demo just empties it).
    private func tellHeld() async {
        if demo != nil { status?.held = nil; return }
        await act { try await call.api.tellHeld() }
    }

    private func say(_ text: String) async -> Bool {
        if demo != nil {  // the demo shows the line; no Mac answers it
            let id = (status?.talk?.map(\.id).max() ?? 0) + 1
            status?.talk = (status?.talk ?? []) + [API.Turn(id: id, who: "user", text: text, understood: nil, typed: true, corrected: false)]
            return true
        }
        #if DEBUG
        NetProbe.sent(text)
        #endif
        let line = outbox.add(text)
        Task { await deliver(line.id) }
        return true  // the field clears now: the line shows as Sending, then Sent, or stays with Retry
    }

    private func resend(_ id: String) {
        outbox.sending(id)
        Task { await deliver(id) }
    }

    /// One typed line to the Mac, sent again with the same id while the Mac does not answer (it takes it once).
    private func deliver(_ id: String) async {
        for wait in Outbox.resendWaits + [nil] {
            guard let line = outbox.line(id) else { return }
            do {
                let turn = try await call.api.say(line.text, id: id)
                outbox.sent(id, turn: turn)
                problem = nil
                await refreshStatus()
                return
            } catch API.Failure.status(let code, let detail) {
                outbox.failed(id, why: code == 409 && detail == "no call is up" ? "Start the call first." : Self.refusal(code, detail))
                return
            } catch {
                guard let wait else { break }
                try? await Task.sleep(for: .seconds(wait))
            }
        }
        outbox.failed(id, why: TypedCopy.noAnswer)
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
        if let fresh = try? await call.api.status() {
            status = fresh
            outbox.settle(fresh.talk ?? [])
        }
    }

    #if DEBUG
    /// Debug builds, for apps/ios/e2e/bad_network.py: typed lines at set seconds after the call is up (POINTE_TYPE_AT), through
    /// the same `say` as Send, so the UI test need not touch the screen (each touch reads the whole screen on the main
    /// thread, and would be measured as the app's own stall).
    private func typeOnCue() async {
        let times = (ProcessInfo.processInfo.environment["POINTE_TYPE_AT"] ?? "").split(separator: ",").compactMap { Double($0) }
        guard !times.isEmpty else { return }
        while call.state != .live { try? await Task.sleep(for: .milliseconds(100)) }
        let up = Date()
        for (n, at) in times.enumerated() {
            try? await Task.sleep(for: .seconds(max(0, at - Date().timeIntervalSince(up))))
            _ = await say("status of the rollout part \(n + 1)")
        }
    }
    #endif

    private func poll() async {
        while !Task.isCancelled {
            call.checkHealth()  // a call that went quiet is redialled, not left showing "Listening"
            do {
                let fresh = try await call.api.status()
                if fresh != status { status = fresh }
                if !outbox.lines.isEmpty { outbox.settle(fresh.talk ?? []) }
                call.follow(fresh.ptt)
                await AlertCenter.shared.sync(fresh.attention, api: call.api, machines: MachineView(fresh))
                reach = .ok
                trouble = link.problem(version: fresh)
            } catch API.Failure.status(let code, _) where code == 401 || code == 403 {
                reach = .rejected  // the Mac answers, and refuses this phone's key: not the same as the Mac being away
                trouble = link.problem(status: code)
            } catch {
                reach = .unreachable
                trouble = link.problem(error, pinRefused: call.api.pinRefused)
            }
            shell?.polled(status, reach: reach)
            // Live words need a quick refresh while the call is up; idle, once a second is enough.
            try? await Task.sleep(nanoseconds: call.state == .live ? 400_000_000 : 1_000_000_000)
        }
    }

    /// Approving needs Face ID (or the passcode): the phone may be unlocked in someone else's hand. Denying never does.
    /// Nil when it went to the Mac or the person cancelled the check; otherwise why nothing happened.
    private func answer(_ s: API.Session, _ allow: Bool) async -> String? {
        if allow {
            let context = LAContext()
            do {
                guard try await context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: Self.ownerReason("Approve what \(s.name) wants to run"))
                else { return OwnerCopy.notChecked }
            } catch {
                return OwnerCopy.refusal((error as? LAError)?.code)
            }
        }
        if demo != nil { demoAnswered.insert(s.request_id ?? ""); return nil }
        _ = await act { try await call.api.answer(s, allow: allow) }  // a refusal from the Mac is the screen's problem line
        return nil
    }
}

/// Where the conversation is scrolled to, and how much room it has.
struct ScrollPin: Equatable {
    let bottom: Bool
    let room: CGFloat
    var offset: CGFloat = 0

    /// Within this of the newest line counts as at it.
    static let slack: CGFloat = 48

    init(bottom: Bool, room: CGFloat, offset: CGFloat = 0) {
        self.bottom = bottom
        self.room = room
        self.offset = offset
    }

    init(_ geo: ScrollGeometry) {
        self.init(offset: geo.contentOffset.y, container: geo.containerSize.height, content: geo.contentSize.height)
    }

    /// `container` is what shows between the insets (the dock's is already off it), and at the end the offset plus it is
    /// the content's height. Taking the dock's inset off a second time put the end a dock's height past anything a finger
    /// or a scroll can reach: the view never knew it was back at the end, and the New pill stayed.
    init(offset: CGFloat, container: CGFloat, content: CGFloat) {
        self.init(bottom: offset + container >= content - Self.slack, room: container, offset: offset)
    }
}

/// Only your own finger takes the conversation off the newest line. When the keyboard, the type bar or a card takes room
/// (or gives it back), the view goes back to the end, so nothing new hides behind the controls.
struct ScrollFollow: Equatable {
    private(set) var atBottom = true
    private(set) var unseen = false
    private var scrolling = false
    private var animating = false  // a scroll to the end is under way: it gets there by itself
    private var pinned = true  // the last position seen was the end
    private var endOffset: CGFloat?  // the offset when the view was last at the end

    /// The position moved. True when the view should go back to the end: no finger moved it. Off the end yet still
    /// within the slack of where the end was, the content grew under the view (a new line while the list glides, and the
    /// glide settling a point back): that is not a finger taking the view away, or the pill came back at the end.
    mutating func moved(bottom: Bool, offset: CGFloat = 0) -> Bool {
        if bottom {
            endOffset = offset
            pinned = true
            atBottom = true
            unseen = false
            return false
        }
        if let endOffset, pinned, offset >= endOffset - ScrollPin.slack { return atBottom }
        pinned = false
        if scrolling { atBottom = false }
        return atBottom
    }

    /// A finger on the conversation, or let go. The phase can arrive after the drag's first move, and the position does
    /// not change again to say so: that move counts now.
    mutating func phase(scrolling: Bool, animating: Bool = false) {
        self.scrolling = scrolling
        self.animating = animating
        if scrolling && !pinned { atBottom = false }
    }

    /// The New pill was tapped: following again from now, before the scroll reaches the end.
    mutating func jumpToEnd() {
        atBottom = true
        unseen = false
    }

    /// A new line, or new words heard. True when the view follows them to the end; otherwise the New pill shows.
    mutating func newLine() -> Bool {
        if atBottom { return true }
        unseen = true
        return false
    }

    /// A scroll back to the end, deferred a turn, still applies: no finger came down meanwhile, and no animated scroll
    /// is already on its way there (jumping would cut it short).
    var stillFollowing: Bool { atBottom && !scrolling && !animating }
    var pillShown: Bool { unseen && !atBottom }
}

/// What the call is doing, in one glance, with the mute button beside it.
struct StatusLine: View {
    struct Mute {
        let on: Bool
        let held: Bool
        let toggle: () -> Void
    }

    let title: String
    let subtitle: String
    let phase: Call.State
    let muted: Bool
    let speaking: Bool
    var broken = false  // a refused key: red, never the green of a call that hears
    var mute: Mute? = nil
    var skip: (() -> Void)? = nil  // only while Pointe speaks (SkipRule): the line being said, skipped

    private var dot: StateDot.Kind { StateDot.kind(title: title, speaking: speaking) }

    private var tint: Color {
        switch phase {
        case .live: return broken ? Brand.danger : muted ? Brand.dim : dot.pointesTurn ? Brand.orange : Brand.success
        case .connecting, .reconnecting: return Brand.orange
        case .off: return Brand.dim
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 8) {
                HStack(alignment: .firstTextBaseline, spacing: 10) {  // the dot belongs to the state: on its first line, however long
                    StateDot(kind: phase == .live && !broken && !muted ? dot : .steady, tint: tint)
                        .alignmentGuide(.firstTextBaseline) { $0[.bottom] + 3 }
                    Text(title).font(.brand(.title3)).contentTransition(.opacity)
                }
                // One element with the line under it, as before the button sat between them.
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("\(title), \(subtitle)")
                .accessibilityIdentifier("statusLine")
                if let mute {  // right beside the state, and its own element
                    MuteButton(on: mute.on, held: mute.held, toggle: mute.toggle).padding(.vertical, -6)
                }
                if let skip {  // after it, so the mute button never moves when this one comes and goes
                    SkipButton(skip: skip).padding(.vertical, -6).transition(.opacity)
                }
            }
            Text(subtitle.unbrokenCommands).font(.brand(.subheadline)).foregroundStyle(Brand.muted).lineLimit(2)
                .padding(.leading, 18)
                .accessibilityHidden(true)
        }
        .motion(.easeInOut(duration: 0.2), value: title)
    }
}

struct RequestCard: View {
    let session: API.Session
    /// "shop · devbox" when its machine needs saying.
    var who: String? = nil
    var showAgent = false
    /// Who answers it (a machine with people): while somebody else is asked first the card says who and for how long,
    /// and offers no answer.
    var turn: MachineView? = nil
    /// Nil when it was sent (or the owner check was cancelled); otherwise why not, shown under the buttons.
    let answer: (API.Session, Bool) async -> String?
    @State private var busy = false
    @State private var refusal: String?
    @State private var answered = 0
    @State private var cardHeight: CGFloat = 0
    @State private var boxHeight: CGFloat = 0
    @Environment(\.dynamicTypeSize) private var typeSize
    @Environment(\.dockRoom) private var room

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // At the accessibility sizes the agent's badge goes under the name: beside it, a long name broke inside its words.
            let head = typeSize.isAccessibilitySize ? AnyLayout(VStackLayout(alignment: .leading, spacing: 6)) : AnyLayout(HStackLayout(spacing: 6))
            head {
                Label { Text("\(who ?? session.name) needs approval") } icon: { Image(systemName: "hand.raised.fill").foregroundStyle(Brand.accent) }
                    .font(.brand(.headline))
                if showAgent { AgentBadge(session: session).accessibilityIdentifier("requestAgent") }
            }
            if let what = parsed.what { Text(what).font(.brand(.subheadline)).foregroundStyle(Brand.muted) }
            // A long command scrolls in its box, which gives up height to the rest of the card when the dock is short.
            FitScroll(limit: Self.commandLimit(room: room, chrome: cardHeight - boxHeight)) {
                Text(parsed.exact)  // word for word: this is what Approve runs
                    .font(.system(.footnote, design: .monospaced)).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
            }
            .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { boxHeight = $0 }
            .background(Brand.raised, in: RoundedRectangle(cornerRadius: 12))
            .accessibilityIdentifier("requestCommand")
            if session.isOffline {  // its machine dropped: the prompt is back in its terminal, and an answer would be stale
                Label(MachinesCopy.offlineCard, systemImage: "bolt.horizontal.circle")
                    .font(.brand(.subheadline)).foregroundStyle(Brand.muted)
                    .accessibilityIdentifier("requestOffline")
            } else if let turn, turn.waitsFor(session) != nil {
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    Label(turn.askedLine(session, now: context.date) ?? "", systemImage: "hourglass")
                        .font(.brand(.subheadline).monospacedDigit()).foregroundStyle(Brand.muted)
                }
                .accessibilityIdentifier("requestAskedFirst")
            } else {
                if let turn {  // on the machine itself: its owner may answer at once, and sees who is asked
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        if let line = turn.askedLine(session, now: context.date) {
                            Text(line).font(.brand(.caption).monospacedDigit()).foregroundStyle(Brand.muted)
                                .accessibilityIdentifier("requestAskedFirst")
                        }
                    }
                }
                Text(session.voice_can_approve == true ? "Say yes or no, or \(Surface.tap)." : "Has a secret, never said aloud: check it, then \(Surface.tap).")
                    .font(.brand(.caption)).foregroundStyle(Brand.muted)
                ViewThatFits(in: .horizontal) {  // side by side while both words fit whole, else one over the other
                    HStack(spacing: 10) { deny; approve }
                    VStack(spacing: 10) { approve; deny }
                }
                .disabled(busy)
                if let refusal {
                    Text(refusal).font(.brand(.caption)).foregroundStyle(Brand.accent).fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("requestRefusal")
                }
            }
        }
        .padding(16)
        .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { cardHeight = $0 }
        .background(Brand.card, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.orangeLine))
        .sensoryFeedback(.warning, trigger: session.request_id)
        .sensoryFeedback(.success, trigger: answered)
    }

    private var deny: some View {
        Button { act(false) } label: { Text("Deny").lineLimit(1).fixedSize().frame(maxWidth: .infinity) }
            .buttonStyle(.brandQuiet).controlSize(.large).accessibilityIdentifier("requestDeny")
    }

    private var approve: some View {
        Button { act(true) } label: { Label("Approve", systemImage: Surface.ownerSymbol).lineLimit(1).fixedSize().frame(maxWidth: .infinity) }
            .buttonStyle(.brandPrimary).controlSize(.large).accessibilityIdentifier("requestApprove")
    }

    /// The command box's height: up to 150 points, less when the dock leaves the card less than its whole height (the
    /// rest of the card is `chrome`), and never under two lines, so the command is always there to read.
    static func commandLimit(room: CGFloat, chrome: CGFloat) -> CGFloat {
        guard room.isFinite, chrome > 0 else { return 150 }
        return min(150, max(56, room - chrome))
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
        refusal = nil
        Task {
            refusal = await answer(session, allow)
            busy = false
            if refusal == nil { answered += 1 }
        }
    }
}

/// A machine's name, as a sheet item.

struct MachineName: Identifiable, Equatable { let id: String }
