import Carbon.HIToolbox
import PointeKit
import PointeMacKit
import SwiftUI

/// Settings (⌘,). What belongs to this Mac is kept here; the microphone mode, the patience and the voice lock are the
/// daemon's, shared with the page and the phone.
struct SettingsView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        TabView {
            GeneralSettings().tabItem { Label("General", systemImage: "gearshape") }
            VoiceSettings().tabItem { Label("Voice", systemImage: "waveform") }
            DaemonSettings().tabItem { Label("Pointe on this Mac", systemImage: "desktopcomputer") }
        }
        .frame(width: 520)
        .onAppear { model.refreshKeys() }
    }
}

private struct GeneralSettings: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        Form {
            Picker(Theme.setting, selection: $model.theme) {
                ForEach(Theme.allCases) { Text($0.label).tag($0) }
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier("settings.theme")

            Toggle("Open Pointe at login", isOn: Binding(get: { model.loginItem }, set: { model.setLoginItem($0) }))
                .accessibilityIdentifier("settings.login")
            if let note = model.loginNote { Text(note).font(.footnote).foregroundStyle(Brand.accent) }

            Toggle("Show the call bubble", isOn: $model.bubbleOn).accessibilityIdentifier("settings.bubble")
            Text("A small panel that floats over other apps with the state and a talk button.").font(.footnote).foregroundStyle(.secondary)

            Section("Alerts") {
                Toggle("Notify me when a session needs me", isOn: $model.alertsOn).accessibilityIdentifier("settings.alerts")
                Toggle("Approve from notifications", isOn: Binding(get: { model.store.prefs?.watchApprove == true },
                                                                    set: { on in Task { await model.store.setApproveFromNotifications(on) } }))
                    .disabled(model.store.prefs == nil)
                Text("A notification shows what Pointe would read out, never the hidden full text. Its Approve is offered only for a request Pointe can read out; anything else opens the window, where Approve asks for Touch ID or your password. This setting is shared with the page and the phone.")
                    .font(.footnote).foregroundStyle(.secondary)
            }

            Section(AboutCopy.title) {
                LabeledContent(AboutCopy.version, value: model.appVersion)
                Text(AboutCopy.body).font(.footnote).foregroundStyle(.secondary)
                if let url = URL(string: AboutCopy.repoURL) { Link(AboutCopy.repo, destination: url) }
            }
        }
        .formStyle(.grouped)
    }
}

private struct VoiceSettings: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        let store = model.store
        Form {
            Section("Microphone") {
                Picker("Microphone", selection: Binding(get: { store.prefs?.microphone ?? "always" },
                                                        set: { mode in Task { await store.setMicrophone(mode) } })) {
                    Text("Always on").tag("always")
                    Text("Push to talk").tag("ptt")
                }
                .pickerStyle(.segmented)
                .accessibilityIdentifier("settings.microphone")
                Picker("Talk button", selection: $model.talkStyle) {
                    ForEach(TalkStyle.allCases, id: \.self) { Text($0.label).tag($0) }
                }
                .pickerStyle(.segmented)
                .accessibilityIdentifier("settings.talkStyle")
                Text("With push to talk, nothing leaves this Mac unless you hold the talk control. \(model.talkStyle.hint)")
                    .font(.footnote).foregroundStyle(.secondary)
            }

            Section("Shortcut, from any app") {
                LabeledContent("Talk") { ShortcutRecorder() }
                if let note = model.shortcutNote {
                    Text(note).font(.footnote).foregroundStyle(Brand.accent).accessibilityIdentifier("settings.shortcutNote")
                } else if model.shortcut != nil {
                    Label(model.shortcutSeen ? "It arrived: the shortcut is yours." : "Press it now to check that nothing else uses it.",
                          systemImage: model.shortcutSeen ? "checkmark.circle.fill" : "keyboard")
                        .font(.footnote).foregroundStyle(model.shortcutSeen ? Brand.successText : .secondary)
                        .accessibilityIdentifier("settings.shortcutSeen")
                }
                Text("On a call with push to talk: hold it to talk, let go to send (or press to start and again to send, with Tap to talk). With Always on, it mutes. It needs no Accessibility or Input Monitoring permission.")
                    .font(.footnote).foregroundStyle(.secondary)
            }

            Section(TurnsCopy.setting) {
                Picker(TurnsCopy.setting, selection: Binding(get: { store.prefs?.patience ?? TurnsCopy.defaultLevel },
                                                             set: { level in Task { await store.setPatience(level) } })) {
                    ForEach(TurnsCopy.levels, id: \.value) { Text($0.label).tag($0.value) }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .accessibilityIdentifier("settings.patience")
            }

            Section("Voice lock") {
                let lock = store.status?.voice_lock
                Picker("Only your voice counts for", selection: Binding(get: { lock?.lockLevel ?? .off },
                                                                        set: { level in Task { await store.setVoiceLock(level) } })) {
                    ForEach(VoiceLockLevel.allCases) { Text($0.label).tag($0) }
                }
                .disabled(lock == nil)
                .accessibilityIdentifier("settings.voiceLock")
                Text((lock?.lockLevel ?? .off).help).font(.footnote).foregroundStyle(.secondary)
                if lock?.isEnrolled != true {
                    HStack {
                        Text("Enrol your voice to use the other levels.").font(.footnote).foregroundStyle(.secondary)
                        Button("Enrol on the page…") { model.openPage() }.buttonStyle(.link)
                    }
                }
            }

            if store.prefs == nil {
                Text(MacCopy.daemonDown).font(.footnote).foregroundStyle(Brand.accent)
            }
            if let notice = store.notice { Text(notice).font(.footnote).foregroundStyle(Brand.accent).accessibilityIdentifier("settings.notice") }
        }
        .formStyle(.grouped)
        .task { await store.loadPrefs() }
    }
}

private struct DaemonSettings: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Form {
            Section("Pointe on this Mac") {
                LabeledContent("State") { Text(model.daemonLine).multilineTextAlignment(.trailing).textSelection(.enabled) }
                    .accessibilityIdentifier("settings.daemon")
                LabeledContent("This app", value: model.appVersion)
                LabeledContent("Plugin", value: model.plugin.map { "version \($0.version)" } ?? "not found")
                if let note = model.store.versionNote {
                    Text("\(note.line) \(note.fix)").font(.footnote).foregroundStyle(Brand.accent).textSelection(.enabled)
                }
                if let local = model.store.status?.local { LabeledContent("Models", value: local.short) }
                HStack {
                    Button("Start") { Task { await model.startDaemon() } }
                        .disabled(model.plugin == nil || model.daemon == .running || model.daemon == .starting || model.daemon == .node)
                    Button("Restart") { Task { await model.restartDaemon() } }
                        .disabled(model.plugin == nil || model.daemon == .starting || model.daemon == .node)
                    if model.daemon == .starting { ProgressView().controlSize(.small) }
                    Spacer()
                    Button(MacCopy.openPage) { model.openPage() }.disabled(model.daemon != .running)
                }
                Text("Restart ends the call and starts Pointe again on the plugin's current code, as /pointe:stop and /pointe:voice do.")
                    .font(.footnote).foregroundStyle(.secondary)
            }

            Section("Model keys") {
                ForEach(Vendor.allCases) { vendor in
                    LabeledContent(vendor.label) {
                        HStack {
                            let has = model.keys[vendor] == true
                            Label(has ? "In the Keychain" : "Missing", systemImage: has ? "checkmark.circle.fill" : "circle")
                                .foregroundStyle(has ? Brand.successText : .secondary)
                            Button(has ? "Replace…" : "Add…") { Task { await model.addKey(vendor) } }
                                .disabled(model.plugin == nil)
                                .accessibilityLabel("\(has ? "Replace" : "Add") the \(vendor.label) key")
                        }
                    }
                    .accessibilityIdentifier("settings.key.\(vendor.rawValue)")
                }
                if let note = model.keyNote { Text(note).font(.footnote).foregroundStyle(.secondary) }
                Text("Keys stay in your Keychain. This app only checks that one is there: it never reads, shows or stores a key. Add… opens Pointe's own window, which hands the key to the Keychain. Restart Pointe to use a new key.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
    }
}

/// Records the system-wide shortcut: click, then press the combination. Esc cancels, Delete removes the shortcut. While
/// recording, the keys go to this window only (a local monitor): nothing is read from other apps.
struct ShortcutRecorder: View {
    @Environment(AppModel.self) private var model
    @State private var recording = false
    @State private var monitor: Any?

    var body: some View {
        Button(recording ? "Press the keys…" : (model.shortcut?.display ?? "None")) {
            recording ? stop() : start()
        }
        .accessibilityLabel(recording ? "Recording the shortcut: press the keys" : "Talk shortcut: \(model.shortcut?.spoken ?? "none")")
        .accessibilityHint("Activate, then press a key combination. Escape cancels, Delete removes it.")
        .accessibilityIdentifier("settings.shortcut")
        .onDisappear(perform: stop)
    }

    private func start() {
        recording = true
        monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            let (key, flags) = (event.keyCode, event.modifierFlags.intersection(.deviceIndependentFlagsMask))
            MainActor.assumeIsolated { record(key: key, flags: flags) }
            return nil  // while recording, every key is the recorder's
        }
    }

    private func stop() {
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil
        recording = false
    }

    private func record(key: UInt16, flags: NSEvent.ModifierFlags) {
        if key == UInt16(kVK_Escape), flags.intersection([.command, .option, .control, .shift]).isEmpty {
            stop()
            return
        }
        if key == UInt16(kVK_Delete) || key == UInt16(kVK_ForwardDelete), flags.intersection([.command, .option, .control]).isEmpty {
            model.shortcut = nil
            stop()
            return
        }
        var modifiers: UInt32 = 0
        if flags.contains(.command) { modifiers |= Shortcut.command }
        if flags.contains(.option) { modifiers |= Shortcut.option }
        if flags.contains(.control) { modifiers |= Shortcut.control }
        if flags.contains(.shift) { modifiers |= Shortcut.shift }
        model.shortcut = Shortcut(keyCode: UInt32(key), modifiers: modifiers)
        stop()
    }
}
