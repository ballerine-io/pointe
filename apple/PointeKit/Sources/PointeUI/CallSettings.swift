import SwiftUI

/// What the Settings sheet (the ••• button at the top) shows: values only, compared as a whole. A status poll that
/// changes none of them leaves the sheet alone. It replaced a Menu of some twenty items that SwiftUI built again on every
/// poll: the open menu jumped back to its top with a fade while you scrolled it.
struct CallSettingsModel: Equatable, Sendable {
    var microphone = "always"
    var talkStyle = TalkStyle.hold
    var patience = TurnsCopy.defaultLevel
    var polish = false
    var whisper: Bool?  // nil: this Mac has no whisper mode
    var machines = false
    var meetingOn = false
    var meetingEnded = false
    var challengeOn = false
    var challengeOpen = false  // a challenge can start or end now: a call up, no meeting, brain dump or drive
    var dictionary = false
    var voiceLock = false
    var conflicts = false
    var showOnPhone = false
    var drive = false
    var driveSuggest = false
    var local: String?
    var demo = false  // "Try a demo": the last row leaves it instead of unpairing

    init() {}

    init(status: API.Status?, prefs: API.Prefs?, microphone: String, talkStyle: TalkStyle, live: Bool, dumping: Bool,
         driving: Bool, driveSuggest: Bool, demo: Bool) {
        self.microphone = microphone
        self.talkStyle = talkStyle
        patience = prefs?.patience ?? TurnsCopy.defaultLevel
        polish = status?.polish ?? false
        whisper = status?.whisper.map { $0.on }
        machines = status?.machines != nil
        meetingOn = status?.meeting?.isOn == true
        meetingEnded = status?.meeting?.isEnded == true
        challengeOn = status?.challenge?.on == true
        challengeOpen = live && !meetingOn && !dumping && !driving  // never both: driving wins
        dictionary = status?.dictionary != nil
        voiceLock = status?.voice_lock != nil
        conflicts = status?.conflicts != nil
        showOnPhone = status?.show_on_phone != nil
        drive = status?.drive != nil
        self.driveSuggest = driveSuggest
        local = status?.local?.short
        self.demo = demo
    }
}

/// A sheet of its own, opened from Settings once Settings has closed (one sheet at a time).
enum CallSettingsLink: Equatable {
    case sessions, machines, meetingStart, meetingEnd, briefing, briefingSettings, meetingSettings, alerts, dictionary,
         voiceLock, conflicts, show, about, phone, nightShift
}

/// What the rows do. Not compared: the closures are new on every render of the call and change nothing that shows.
struct CallSettingsActions {
    var setMicrophone: (String) -> Void = { _ in }
    var setTalkStyle: (TalkStyle) -> Void = { _ in }
    var setPatience: (String) -> Void = { _ in }
    var setPolish: (Bool) -> Void = { _ in }
    var setWhisper: (Bool) -> Void = { _ in }
    var setDriveSuggest: (Bool) -> Void = { _ in }
    var open: (CallSettingsLink) -> Void = { _ in }
    var challenge: () -> Void = {}
    var unpair: () -> Void = {}
}

/// Every setting and screen the call has, grouped, in a list that scrolls like any other: the microphone first.
struct CallSettingsSheet: View, Equatable {
    let model: CallSettingsModel
    var act = CallSettingsActions()
    @AppStorage(Theme.key) private var theme = Theme.fallback.rawValue
    @Environment(\.dismiss) private var dismiss
    @State private var polishWanted: Bool?  // a switch moves at the tap; the Mac's word replaces it on the next status
    @State private var whisperWanted: Bool?
    @State private var unpairAsked = false
    #if os(macOS)
    @Environment(\.macSettings) private var macSections
    #endif

    nonisolated static func == (a: Self, b: Self) -> Bool { a.model == b.model }

    var body: some View {
        NavigationStack {
            BrandForm {
                KickerSection("Microphone") {
                    Picker(selection: Binding(get: { model.microphone }, set: { act.setMicrophone($0) })) {
                        Text("Always on").tag("always")
                        Text("Push to talk").tag("ptt")
                    } label: { Label("Microphone", systemImage: "mic") }
                        .pickerStyle(.menu)
                        .accessibilityIdentifier("microphoneSetting")
                    if model.microphone == "ptt" {
                        Picker(selection: Binding(get: { model.talkStyle }, set: { act.setTalkStyle($0) })) {
                            ForEach(TalkStyle.allCases, id: \.self) { Text($0.label).tag($0) }
                        } label: { Label("Talk button", systemImage: "hand.tap") }
                            .pickerStyle(.menu)
                            .accessibilityIdentifier("talkStyleSetting")
                    }
                    Picker(selection: Binding(get: { model.patience }, set: { act.setPatience($0) })) {
                        ForEach(TurnsCopy.levels, id: \.value) { level in Text(level.label).tag(level.value) }
                    } label: { Label(TurnsCopy.setting, systemImage: "hourglass") }
                        .pickerStyle(.menu)
                        .accessibilityIdentifier("patienceSetting")
                }
                KickerSection("Your words") {
                    Toggle(isOn: Binding(get: { polishWanted ?? model.polish }, set: { polishWanted = $0; act.setPolish($0) })) {
                        Label("Clean up my words", systemImage: "wand.and.sparkles")
                    }
                    if let whisper = model.whisper {
                        Toggle(isOn: Binding(get: { whisperWanted ?? whisper }, set: { whisperWanted = $0; act.setWhisper($0) })) {
                            Label(WhisperCopy.button, systemImage: "waveform.badge.minus")
                        }
                        .accessibilityIdentifier("whisperItem")
                    }
                    if model.dictionary {
                        row(VocabularyCopy.menuItem, "text.book.closed", .dictionary).accessibilityIdentifier("dictionaryItem")
                    }
                }
                KickerSection("Call") {
                    row("Sessions and mode", "rectangle.stack", .sessions)
                    if model.machines { row(MachinesCopy.title, "desktopcomputer", .machines).accessibilityIdentifier("machinesItem") }
                    #if os(macOS)  // the Mac is the side that shows the code a phone pairs with
                    if !model.demo { row(PhoneCopy.title, "iphone", .phone).accessibilityIdentifier("phoneItem") }
                    #endif
                    if !model.meetingOn { row("Start a meeting", "person.3", .meetingStart) }
                    if model.meetingEnded { row("The meeting that ended", "doc.text", .meetingEnd).accessibilityIdentifier("reopenMeetingEnd") }
                    row(BriefingCopy.title, "sun.horizon", .briefing)
                    row(NightShiftCopy.title, "moon.stars", .nightShift).accessibilityIdentifier("nightShiftItem")
                    Button { dismiss(); act.challenge() } label: {
                        Label(model.challengeOn ? ChallengeCopy.end : ChallengeCopy.menuItem, systemImage: "figure.fencing")
                    }
                    .disabled(!model.challengeOpen)
                    .accessibilityIdentifier("menu.challenge")
                }
                KickerSection("More settings") {
                    row(BriefingCopy.settingsItem, "clock", .briefingSettings)
                    row("Meeting settings", "gearshape", .meetingSettings)
                    row(AlertCopy.section, "bell.badge", .alerts)
                    if model.voiceLock { row(VoiceLockCopy.title, "lock.shield", .voiceLock) }
                    if model.conflicts { row(ConflictCopy.settingsTitle, "exclamationmark.triangle", .conflicts) }
                    if model.showOnPhone { row(ShowCopy.setting, "doc.text.magnifyingglass", .show).accessibilityIdentifier("showSettingItem") }
                    #if os(iOS)  // a Mac has no motion sensor and no car's audio route: nothing to suggest from
                    if model.drive {
                        Toggle(isOn: Binding(get: { model.driveSuggest }, set: { act.setDriveSuggest($0) })) {
                            Label(DriveCopy.suggestSetting, systemImage: "car")
                        }
                        .accessibilityIdentifier("driveSuggestSetting")
                    }
                    #endif
                    Picker(selection: $theme) {
                        ForEach(Theme.allCases) { Text($0.label).tag($0.rawValue) }
                    } label: { Label(Theme.setting, systemImage: "circle.lefthalf.filled") }
                        .pickerStyle(.menu)
                        .accessibilityIdentifier("appearanceSetting")
                }
                Section {
                    if let line = model.local { Label(line, systemImage: "desktopcomputer").accessibilityIdentifier("localMode") }  // read-only
                    row(AboutCopy.title, "info.circle", .about).accessibilityIdentifier("aboutSetting")
                }
                #if os(macOS)
                macSections  // what belongs to this Mac alone: the shortcut, the bubble, Pointe on this Mac, its keys
                if model.demo {
                    Section { Button(DemoBadge.exit, systemImage: "xmark.circle") { dismiss(); act.unpair() } }
                }
                #else
                Section {
                    if model.demo {
                        Button(DemoBadge.exit, systemImage: "xmark.circle") { dismiss(); act.unpair() }
                    } else {
                        Button("Unpair this phone", systemImage: "iphone.slash", role: .destructive) { unpairAsked = true }
                            // Then Face ID or the passcode (PairingFlow.unpair): a first pairing asks for neither.
                            .confirmationDialog("Unpair this phone?", isPresented: $unpairAsked, titleVisibility: .visible) {
                                Button("Unpair", role: .destructive) { dismiss(); act.unpair() }
                            } message: {
                                Text("It stops talking to your Mac until you scan its code again.")
                            }
                    }
                }
                #endif
            }
            .buttonStyle(BrandRowButtonStyle())
            .onChange(of: model.polish) { polishWanted = nil }
            .onChange(of: model.whisper) { whisperWanted = nil }
            .sheetTitle("Settings")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() }.buttonStyle(.automatic) } }
        }
    }

    /// A row that opens its own sheet: this one closes first.
    private func row(_ title: String, _ symbol: String, _ link: CallSettingsLink) -> some View {
        Button { act.open(link) } label: { Label(title, systemImage: symbol) }
    }
}
