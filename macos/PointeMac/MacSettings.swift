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
            LabeledContent("Talk shortcut") {
                VStack(alignment: .trailing, spacing: 4) {
                    ShortcutRecorder()
                    if let note = model.shortcutNote {
                        Text(note).font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.accent).accessibilityIdentifier("settings.shortcutNote")
                    } else if model.shortcut != nil {
                        Text(model.shortcutSeen ? "It arrived: nothing else owns it." : "Press it now to check that it arrives.")
                            .font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.muted).accessibilityIdentifier("settings.shortcutSeen")
                    }
                }
            }
            Toggle("Show the call bubble", isOn: $model.bubbleOn).accessibilityIdentifier("settings.bubble")
            Toggle("Open Pointe at login", isOn: Binding(get: { model.loginItem }, set: { model.setLoginItem($0) }))
                .accessibilityIdentifier("settings.login")
            if let note = model.loginNote { Text(note).font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.accent) }
        } header: {
            Text("This Mac")
        } footer: {
            Text("The shortcut talks from any app: in push to talk it is the talk button, in Always on it mutes, and with no call it brings Pointe forward. The bubble is a small panel that floats over other apps with the state and a talk button.")
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
            ForEach(Vendor.allCases) { vendor in
                LabeledContent(vendor.label) {
                    HStack {
                        let has = model.keys[vendor] == true
                        Label(has ? "In the Keychain" : "Missing", systemImage: has ? "checkmark.circle.fill" : "circle")
                            .foregroundStyle(has ? PointeLook.successText : PointeLook.muted)
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
            Text("Keys stay in your Keychain. This app only checks that one is there: it never reads, shows or stores a key. Add… opens Pointe's own window, which hands the key to the Keychain. Restart Pointe to use a new key.")
        }
        .task { model.refreshKeys() }
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
        .buttonStyle(.bordered)
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
