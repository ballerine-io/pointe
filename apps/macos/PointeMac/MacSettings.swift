import Carbon.HIToolbox
import PointeKit
import PointeMacKit
import PointeUI
import SwiftUI

/// The sections of Settings that belong to this Mac alone, after the ones every surface has (the shared module draws
/// those: the microphone, the talk button, the wait, appearance, alerts). Rows of a form: the shared sheet is the form.
struct MacSettingsSections: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        Section {
            LabeledContent(Shortcut.Role.talk.label) {
                VStack(alignment: .trailing, spacing: 4) {
                    ShortcutRecorder(role: .talk, shortcut: $model.shortcut)
                    if let note = model.shortcutNote {
                        Text(note).font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.accent).accessibilityIdentifier("settings.shortcutNote")
                    } else if model.shortcut != nil {
                        Text(model.shortcutSeen ? "It arrived: nothing else owns it." : "Press it now to check that it arrives.")
                            .font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.muted).accessibilityIdentifier("settings.shortcutSeen")
                    }
                }
            }
            LabeledContent(Shortcut.Role.skip.label) {
                VStack(alignment: .trailing, spacing: 4) {
                    ShortcutRecorder(role: .skip, shortcut: $model.skipShortcut)
                    if let note = model.skipNote {
                        Text(note).font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.accent).accessibilityIdentifier("settings.skipShortcutNote")
                    }
                }
            }
            // Each of the three always takes a click. The two under the first were switched off whenever the bubble was
            // hidden (its × does that), and a switch that is off and one that takes no click look the same here.
            Toggle("Show the call bubble during calls", isOn: $model.bubbleOn).accessibilityIdentifier("settings.bubble")
            Toggle("Keep it on screen with no call", isOn: $model.bubblePinned).accessibilityIdentifier("settings.bubblePinned")
            Toggle("Small bubble", isOn: $model.bubbleSmall).accessibilityIdentifier("settings.bubbleSmall")
            Toggle("Open Pointe at login", isOn: Binding(get: { model.loginItem }, set: { model.setLoginItem($0) }))
                .accessibilityIdentifier("settings.login")
            if let note = model.loginNote { Text(note).font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.accent) }
        } header: {
            Text("This Mac")
        } footer: {
            Text("The talk shortcut works from any app: in push to talk it is the talk button, in Always on it turns the mic off and on, and with no call it brings Pointe forward. The skip shortcut, from any app too, skips what Pointe is saying and goes on to the next message. The bubble floats over other apps while a call is up: the state, the talk mode and a talk button. Click it to open Pointe, drag it anywhere; − makes it small, × hides it. Keeping it on screen with no call also switches it on.")
        }

        Section {
            LabeledContent("State") { Text(model.daemonLine).multilineTextAlignment(.trailing).textSelection(.enabled) }
                .accessibilityIdentifier("settings.daemon")
            LabeledContent("This app", value: model.appVersion)
            LabeledContent("Plugin", value: model.plugin.map { "version \($0.version)" } ?? "not found")
            if let note = model.versionNote {
                Text("\(note.line) \(note.fix)").font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.accent).textSelection(.enabled)
            }
            HStack {
                Button("Start") { Task { await model.startDaemon() } }
                    .disabled(model.plugin == nil || model.daemon == .running || model.daemon == .starting || model.daemon == .node)
                Button("Restart") { Task { await model.restartDaemon() } }
                    .disabled(model.plugin == nil || model.daemon == .starting || model.daemon == .node)
                if model.daemon == .starting { ProgressView().controlSize(.small) }
                Spacer()
                Button(MacCopy.openPage) { model.openPage() }.disabled(model.daemon != .running)
            }
            .buttonStyle(.bordered)
        } header: {
            Text("Pointe on this Mac")
        } footer: {
            Text("Restart ends the call and starts Pointe again on the plugin's current code, as /pointe:stop and /pointe:voice do.")
        }

        Section {
            let folders = model.folders ?? []
            ForEach(folders, id: \.self) { path in
                LabeledContent {
                    Button("Remove") { Task { await model.setFolders(folders.filter { $0 != path }) } }
                        .buttonStyle(.bordered)
                        .accessibilityLabel("Remove \(path)")
                } label: {
                    Text(path).lineLimit(1).truncationMode(.middle).textSelection(.enabled)
                }
            }
            Button("Add a folder…") {
                let panel = NSOpenPanel()
                panel.canChooseDirectories = true
                panel.canChooseFiles = false
                guard panel.runModal() == .OK, let path = panel.url?.path, !folders.contains(path) else { return }
                Task { await model.setFolders(folders + [path]) }
            }
            .disabled(model.folders == nil)
            .accessibilityIdentifier("settings.folders.add")
            if let note = model.foldersNote { Text(note).font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.accent) }
        } header: {
            Text(NewSessionCopy.foldersTitle)
        } footer: {
            Text(NewSessionCopy.foldersHelp)
        }
        .task { await model.loadFolders() }

        Section {
            SetupPicker()
            if let plan = model.keyPlan {
                Text(plan.line).font(PointeLook.font(.callout))
                    .foregroundStyle(plan.ready ? PointeLook.text : PointeLook.accent)
                    .textSelection(.enabled).accessibilityIdentifier("settings.keys.line")
            }
            ForEach(Vendor.allCases) { vendor in
                LabeledContent(vendor.label) {
                    HStack {
                        let has = model.keys[vendor] == true
                        let state = model.keyPlan?.state(vendor) ?? .optional
                        Label(KeyRow.text(state), systemImage: KeyRow.symbol(state))
                            .foregroundStyle(state == .inUse ? PointeLook.successText : state == .needed ? PointeLook.accent : PointeLook.muted)
                        Button(has ? "Replace…" : "Add…") { Task { await model.addKey(vendor) } }
                            .buttonStyle(.bordered)
                            .disabled(model.plugin == nil)
                            .accessibilityLabel("\(has ? "Replace" : "Add") the \(vendor.label) key")
                    }
                }
                .accessibilityIdentifier("settings.key.\(vendor.rawValue)")
            }
            if let note = model.keyNote { Text(note).font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.muted) }
        } header: {
            Text("Model keys")
        } footer: {
            Text("\(KeyCopy.whatYouNeedTitle) \(KeyCopy.whatYouNeed)\n\n\(KeyCopy.whyKeys)\n\nKeys stay in your Keychain. This app only checks that one is there: it never reads, shows or stores a key. Add… opens Pointe's own window, which hands the key to the Keychain. After Add…, Pointe tries the key with one tiny live call. Restart Pointe to use a new key or setup. Each setup's measured results and sources: docs/setups.md.")
        }
        .task { model.refreshKeys() }
    }
}

/// The setup menu: each row of `setups.SETUPS` with what it is for; choosing one runs `pointe setup <id>`.
struct SetupPicker: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            LabeledContent(KeyCopy.setupLabel) {
                HStack {
                    if model.setupBusy { ProgressView().controlSize(.small) }
                    Menu(SetupChoice.named(model.setupID)?.name ?? KeyCopy.noSetup) {
                        ForEach(SetupChoice.all) { choice in
                            Button("\(choice.name): best for \(choice.pickFor)") { Task { await model.chooseSetup(choice.id) } }
                        }
                    }
                    .fixedSize()
                    .disabled(model.plugin == nil || model.setupBusy)
                    .accessibilityIdentifier("settings.setup")
                }
            }
            if let chosen = SetupChoice.named(model.setupID) {
                Text(chosen.short).font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.muted)
            } else {
                // Beside "Every role is filled", "None chosen" alone reads as a contradiction.
                Text(KeyCopy.noSetupHow).font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.muted)
                    .accessibilityIdentifier("settings.setup.none")
            }
        }
    }
}

/// A key's row: in use, saved but not used, the one key needed, or optional. Never "missing": a key no role needs is
/// not a problem.
enum KeyRow {
    static func text(_ state: KeyPlan.State) -> String {
        switch state {
        case .inUse: KeyCopy.inUse
        case .notUsed: KeyCopy.notUsed
        case .needed: KeyCopy.needed
        case .optional: KeyCopy.optional
        }
    }

    static func symbol(_ state: KeyPlan.State) -> String {
        switch state {
        case .inUse: "checkmark.circle.fill"
        case .notUsed: "checkmark.circle"
        case .needed: "exclamationmark.circle"
        case .optional: "circle.dashed"
        }
    }
}

/// Records a system-wide shortcut, the talk one or the skip one: click, then press the combination. Esc cancels, Delete
/// removes the shortcut. While recording, the keys go to this window only (a local monitor): nothing is read from
/// other apps.
struct ShortcutRecorder: View {
    let role: Shortcut.Role
    @Binding var shortcut: Shortcut?
    @State private var recording = false
    @State private var monitor: Any?

    static func identifier(_ role: Shortcut.Role) -> String { role == .talk ? "settings.shortcut" : "settings.skipShortcut" }

    var body: some View {
        Button(recording ? "Press the keys…" : (shortcut?.display ?? "None")) {
            recording ? stop() : start()
        }
        .buttonStyle(.bordered)
        .accessibilityLabel(recording ? "Recording the shortcut: press the keys" : "\(role.label): \(shortcut?.spoken ?? "none")")
        .accessibilityHint("Activate, then press a key combination. Escape cancels, Delete removes it.")
        .accessibilityIdentifier(Self.identifier(role))
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
            shortcut = nil
            stop()
            return
        }
        var modifiers: UInt32 = 0
        if flags.contains(.command) { modifiers |= Shortcut.command }
        if flags.contains(.option) { modifiers |= Shortcut.option }
        if flags.contains(.control) { modifiers |= Shortcut.control }
        if flags.contains(.shift) { modifiers |= Shortcut.shift }
        shortcut = Shortcut(keyCode: UInt32(key), modifiers: modifiers)
        stop()
    }
}
