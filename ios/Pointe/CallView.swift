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

    /// Show while it says: the Mac sends it only once this phone turned it on; the setting is checked here too, so
    /// turning it off hides the card at once.
    private var showing: API.Showing? { status?.show_on_phone == true ? status?.showing : nil }

    /// What the screen shows: the demo fixture is always live.
    private var phase: Call.State { demo == nil ? call.state : .live }
    private var live: Bool { phase == .live || phase == .reconnecting }
    private var muted: Bool { demo == nil ? call.muted : false }
    private var speaking: Bool { demo == nil ? call.botSpeaking : false }

    private var brainstorming: Bool { brainstormWanted ?? (status?.monologue != nil) }
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

    /// Push to talk: the press here at once, and the Mac's gate as the truth.
    private var talking: Bool { call.talk.isOpen || (call.talk.ptt && status?.ptt?.open == true) }
    private var ringTalk: RingTalk? {
        guard call.talk.ptt else { return nil }
        return RingTalk(talking: talking, press: { call.talkPress(.ring) }, release: { call.talkRelease(.ring) },
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
            } else if brainstorming {
                BrainstormPanel(said: status?.monologue?.said ?? "", hearing: hearing, back: { setBrainstorm(false) },
                                challenge: { Task { await challenge("start") } }, problem: problem)
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
        .animation(.smooth(duration: 0.3), value: brainstorming)
        .animation(.smooth(duration: 0.3), value: driving)
        .onChange(of: status?.drive) {
            call.driving = status?.driving ?? false
            if driving { typing = false }
            DriveNowPlaying.update(status: status, driving: status?.driving ?? false)
        }
        .animation(.smooth(duration: 0.3), value: challengeShown?.id)
        .background(Brand.background.ignoresSafeArea())
        .sheet(isPresented: $showSessions) {
            SessionsSheet(status: status, switchTo: focus, disconnect: disconnect, setMode: setMode)
                .presentationDetents([.medium, .large])
                .presentationBackground(.regularMaterial)
        }
        .sheet(item: $sessionsOn) { on in
            SessionsSheet(status: status, switchTo: focus, disconnect: disconnect, setMode: setMode, section: on.id)
                .presentationDetents([.large])
                .presentationBackground(.regularMaterial)
        }
        .sheet(isPresented: $showMachines) {
            MachinesSheet(status: status, pairing: pairing, ownerCheck: ownerCheck, invite: makeInvite,
                          cancelInvite: cancelInvite, revoke: revokeMachine)
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
        .sheet(isPresented: $showVoiceLock) {
            if let lock = status?.voice_lock {
                VoiceLockSheet(lock: lock, callUp: phase == .live, pushToTalk: status?.ptt?.mode == "ptt", send: voiceprint, ownerCheck: ownerCheck)
                    .presentationDetents([.medium, .large])
                    .presentationBackground(.regularMaterial)
            }
        }
        .sheet(isPresented: $showConflictSettings) {
            ConflictSettingsSheet(load: loadPrefs, save: savePrefs).presentationDetents([.medium, .large])
                .presentationBackground(.regularMaterial)
        }
        .sheet(isPresented: $showBriefing) {
            BriefingSheet(status: status?.briefing, callUp: phase == .live, meetingOn: meeting?.isOn == true,
                          load: loadBriefings, act: briefing)
                .presentationDetents([.medium, .large])
                .presentationBackground(.regularMaterial)
        }
        .sheet(isPresented: $showBriefingSettings) {
            BriefingSettingsSheet(load: { await loadBriefings()?.schedule }, save: saveBriefingSchedule)
                .presentationDetents([.medium, .large])
                .presentationBackground(.regularMaterial)
        }
        .sheet(isPresented: $showAlerts) {
            AlertsSheet(phone: AlertCenter.shared.enabled, watch: prefs?.watchApprove ?? false,
                        setPhone: { await AlertCenter.shared.setEnabled($0) }, setWatch: setWatchApprove)
                .presentationDetents([.medium, .large])
                .presentationBackground(.regularMaterial)
        }
        .sheet(isPresented: $showSheet) {
            ShowSheet(showing: showing, earlier: status?.show_on_phone == true ? status?.shown_earlier ?? [] : [],
                      follow: $showFollow, load: loadArtifact)
                .presentationBackground(.regularMaterial)
        }
        .sheet(isPresented: $showSettings) {
            ShowSettingsSheet(on: status?.show_on_phone == true, set: setShowOnPhone, ownerCheck: ownerCheck)
                .presentationDetents([.medium])
                .presentationBackground(.regularMaterial)
        }
        .onChange(of: showing?.id) { showFollow.follow(showing) }
        .sheet(isPresented: $showDictionary) {
            VocabularySheet(load: loadDictionary, change: changeDictionary, delete: deleteFromDictionary, setLearn: setLearn)
                .presentationDetents([.medium, .large])
                .presentationBackground(.regularMaterial)
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
                IgnoredSheet(ignored: ignored).presentationDetents([.medium, .large]).presentationBackground(.regularMaterial)
            }
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
                                send: { to in await act { try await call.api.sendActions(to: to) } ? nil : problem ?? "" },
                                discard: { await act { try await call.api.discardMeeting() } })
                    .presentationBackground(.regularMaterial)
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
                                     large: status?.whisper?.on == true && status?.whisper?.held == nil) { editing = $0 }
                    if let problem = Self.shownProblem(screen: problem, call: call.problem, mac: status?.problem) {
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
            .holdToTalk(call.talk.ptt && phase == .live, press: { call.talkPress(.caption) }, release: { call.talkRelease(.caption) })
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
                if status?.drive != nil {  // a mode, like a meeting: switched here, so the mic below never moves
                    Button { setDrive(!driving) } label: {
                        Image(systemName: driving ? "car.fill" : "car").font(.subheadline.weight(.semibold))
                            .foregroundStyle(driving ? Brand.orange : .primary)
                            .frame(width: 36, height: 36)
                            .background(driving ? AnyShapeStyle(Brand.orange.opacity(0.25)) : AnyShapeStyle(.thinMaterial), in: Circle())
                    }
                    .buttonStyle(.plain)
                    .disabled(phase != .live && !driving)
                    .accessibilityLabel(DriveCopy.button)
                    .accessibilityIdentifier("driveButton")
                    .accessibilityValue(driving ? "On" : "Off")
                }
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
                         showAll: { showSessions = true }, rename: rename, machines: machines, filter: $machineFilter,
                         showMachine: { sessionsOn = MachineName(id: $0) })
            if let showing {
                ShowCard(showing: showing) { showSheet = true }
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
            HStack(alignment: .top) {
                StatusLine(title: title, subtitle: subtitle, phase: phase, muted: muted, speaking: speaking)
                Spacer(minLength: 8)
                if let n = status?.voice_lock?.ignored?.count, n > 0 {
                    Button(VoiceLockCopy.ignored(n)) { showIgnored = true }
                        .font(.caption).foregroundStyle(.secondary).buttonStyle(.plain)
                        .accessibilityIdentifier("voiceIgnored")
                }
            }
        }
        .padding(.horizontal, 18)
        .padding(.top, 8)
        .padding(.bottom, 10)
        .background(.bar)
        .animation(.snappy, value: showing?.id)
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
            .disabled(phase != .live || meeting?.isOn == true || brainstorming || driving)  // never both: driving wins
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
            if let line = status?.local?.short {
                Section { Label(line, systemImage: "desktopcomputer").accessibilityIdentifier("localMode") }  // read-only
            }
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
                    Text("\(waiting.count - 1) more waiting").font(.caption).foregroundStyle(.secondary)
                }
            }
            if let w = status?.whisper, w.on, w.held == nil, !driving {
                WhisperCard(status: w, suggestPushToTalk: whisperFollow.suggestsPushToTalk(w) && !call.talk.ptt,
                            pushToTalk: { setMicrophone("ptt") }, notNow: { whisperFollow.notNow() },
                            back: { Task { await setWhisper(false) } })
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
            if typing && !driving {
                TypeBar(send: say) { withAnimation(.snappy) { typing = false } }
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
            BottomBar(phase: phase, muted: muted, monologue: brainstorming, typing: typing,
                      mic: micTapped, listen: { setBrainstorm(!brainstorming) }, type: { withAnimation(.snappy) { typing.toggle() } },
                      sessions: { showSessions = true }, hangUp: { call.hangUp() }, talk: ringTalk,
                      driving: driving)
        }
        .padding(.horizontal, 14)
        .padding(.top, 8)
        .padding(.bottom, 4)
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
            if open.count > 1 { Text(ConflictCopy.more(open.count - 1)).font(.caption).foregroundStyle(.secondary) }
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
        status = try? await call.api.status()
        return nil
    }

    /// Three yeses in a row the lock could not place: the tap still works, and re-enrolling may help.
    private var voiceUnsure: Bool { (status?.voice_lock?.unsure_streak ?? 0) >= 3 }
    private var unsureNote: some View {
        Text(VoiceLockCopy.unsure).font(.caption).foregroundStyle(Brand.orange).accessibilityIdentifier("voiceUnsure")
    }

    /// An answerable request first: one whose machine is offline is back in its terminal.
    private var waiting: [API.Session] {
        (status?.sessions.filter { $0.waiting && $0.canApprove } ?? []).enumerated()
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
        case .off: return Self.offTitle(reachable: reachable, macOnACall: status?.connected == true)
        case .connecting: return "Connecting…"
        case .reconnecting: return "Reconnecting…"
        case .live:
            if challengeOn { return ChallengeCopy.state }
            if brainstorming { return "Brainstorming" }
            if call.talk.ptt {
                if talking { return "Talking" }
                if speaking { return "Speaking" }
                if let why = call.talkClosedWhy { return "Talk closed: \(why)" }
                return call.talk.roomHeard ? "Meeting: room is heard · hold to talk" : "Hold to talk"
            }
            return muted ? "Muted" : speaking ? "Speaking" : "Listening"
        }
    }

    /// No call here: the Mac may still have one, on the page or another phone, and a tap would be turned away.
    static func offTitle(reachable: Bool, macOnACall: Bool) -> String {
        !reachable ? "Mac not reachable" : macOnACall ? "On a call elsewhere" : "Not connected"
    }

    private var subtitle: String {
        if !reachable { return "Is Twingate, Tailscale or the same Wi-Fi on for this phone?" }
        guard let status else { return "Reaching your Mac…" }
        if phase == .off { return "Tap the mic to start talking" }
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
                              settings: { showMeetingSettings = true }, reconnect: reconnectAudio)
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
                    .id(handId)  // a new hand gets a new card: never the last one's busy buttons
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                }
                conflictCard(inMeeting: true)
                if let request = waiting.first {
                    RequestCard(session: request, who: machines.label(request), showAgent: (status?.sessions ?? []).mixesAgents, answer: answer)
                    if voiceUnsure { unsureNote }
                }
                if typing {
                    TypeBar(prompt: "Ask Pointe, only you see it", send: { text in await act { try await call.api.ask(text) } }) { withAnimation(.snappy) { typing = false } }
                }
                MeetingBar(meeting: meeting, phase: phase, muted: muted, typing: typing, mic: micTapped,
                           toggleMode: { setMeetingMode(meeting.participating ? "listening" : "participating") },
                           ask: { withAnimation(.snappy) { typing.toggle() } }, speakers: { showSpeakers = true },
                           end: { confirmEnd = true }, talk: ringTalk)
            }
            .padding(.horizontal, 14).padding(.top, 8).padding(.bottom, 4)
            .background(alignment: .bottom) {  // notes scroll under the controls: fade them out instead of overlapping
                LinearGradient(stops: [.init(color: Brand.background.opacity(0), location: 0),
                                       .init(color: Brand.background.opacity(0.92), location: 0.25)],
                               startPoint: .top, endPoint: .bottom)
                    .ignoresSafeArea(edges: .bottom)
                    .allowsHitTesting(false)
            }
            .animation(.snappy, value: handId)
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
            if detail == "No call is up." { return "No call is up. Start one here with the mic, or on the Mac, then start the meeting." }
            return detail.isEmpty ? "The Mac refused." : Self.refusal(409, detail)
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

    // MARK: challenge me

    private var challengeOn: Bool { status?.challenge?.on == true }

    /// On, or ended and not closed here; an ended one gives way to a brainstorm, as on the page.
    private var challengeShown: API.ChallengeStatus? {
        guard let c = status?.challenge, ChallengeCopy.shown(c, dismissed: challengeClosed), c.on || !brainstorming else { return nil }
        return c
    }

    /// start or end. The Mac's refusal is shown as it gives it. The demo plays along on its own status.
    private func challenge(_ action: String) async {
        problem = nil
        if demo != nil {
            if action == "start" {
                status?.challenge = API.ChallengeStatus(id: "demo-\(Int(Date().timeIntervalSince1970))", on: true, since: nil, ended_at: nil,
                                                        plan: status?.monologue?.said ?? "", sessions: [], objections: 0,
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
        status = try? await call.api.status()
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
        status = try? await call.api.status()
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
        status = try? await call.api.status()
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
        status = try? await call.api.status()
        return nil
    }

    // MARK: actions

    private func setMicrophone(_ mode: String) {
        let before = call.talk.mode
        call.setMicrophone(mode)
        Task {
            guard !(await savePrefs(["microphone": mode])) else { return }
            call.setMicrophone(before)  // the Mac's gate is the rule: without it, the phone does not pretend
            problem = "The Mac did not take the microphone setting. Is Pointe on the Mac up to date?"
        }
    }

    private func micTapped() {
        if phase == .live && call.talk.ptt { return }  // the hold opens and closes it
        if phase == .live { call.toggleMute() } else if phase == .off { Task { await call.start() } }
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
                status = try? await call.api.status()
            } catch API.Failure.status(_, let detail) {
                problem = DriveCopy.refused(detail)
            } catch {
                problem = "The Mac did not answer."
            }
            driveWanted = nil  // from here the Mac's word decides
        }
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
            status = try? await call.api.status()
            return nil
        } catch { return .from(error) }
    }

    private func rename(_ name: String, _ newName: String) {
        guard demo == nil else { return }
        Task {
            do {
                try await call.api.rename(name, to: newName)
                problem = nil
                status = try? await call.api.status()
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
        status = try? await call.api.status()
        return true
    }

    private func poll() async {
        while !Task.isCancelled {
            call.checkHealth()  // a call that went quiet is redialled, not left showing "Listening"
            do {
                let fresh = try await call.api.status()
                if fresh != status { status = fresh }
                call.follow(fresh.ptt)
                await AlertCenter.shared.sync(fresh.attention, api: call.api, machines: MachineView(fresh))
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
    /// "shop · devbox" when its machine needs saying.
    var who: String? = nil
    var showAgent = false
    let answer: (API.Session, Bool) async -> Void
    @State private var busy = false
    @State private var answered = 0

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 6) {
                Label { Text("\(who ?? session.name) needs approval") } icon: { Image(systemName: "hand.raised.fill").foregroundStyle(Brand.orange) }
                    .font(.headline)
                if showAgent { AgentBadge(session: session) }
            }
            if let what = parsed.what { Text(what).font(.subheadline).foregroundStyle(.secondary) }
            Text(parsed.exact)  // word for word: this is what Approve runs
                .font(.system(.footnote, design: .monospaced)).textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(12).background(.black.opacity(0.35), in: RoundedRectangle(cornerRadius: 10))
            if session.isOffline {  // its machine dropped: the prompt is back in its terminal, and an answer would be stale
                Label(MachinesCopy.offlineCard, systemImage: "bolt.horizontal.circle")
                    .font(.subheadline).foregroundStyle(.secondary)
                    .accessibilityIdentifier("requestOffline")
            } else {
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

/// A machine's name, as a sheet item.
struct MachineName: Identifiable, Equatable { let id: String }
