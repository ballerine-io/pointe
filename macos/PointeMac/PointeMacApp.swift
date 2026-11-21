import AppKit
import PointeKit
import SwiftUI

/// Pointe for the Mac: a menu bar item, a window for the call, and Settings. It is a client of the daemon on this Mac
/// (docs/design/macos-app.md); with no window open it has no Dock icon.
@main
struct PointeMacApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    private let model = AppModel.shared

    var body: some Scene {
        MenuBarExtra {
            MenuContent().environment(model)
        } label: {
            MenuBarLabel().environment(model)
        }
        .menuBarExtraStyle(.menu)

        Settings {
            SettingsView().environment(model)
        }
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("Open Pointe") { model.windows.showMain() }.keyboardShortcut("o")
                Button(NewSessionCopy.title) { model.newSession() }.keyboardShortcut("n")
                    .disabled(model.daemon != .running)
            }
            CommandMenu("Call") {
                Button(model.call.state == .off ? MacCopy.connect : MacCopy.hangUp) { Task { await model.toggleCall() } }
                    .keyboardShortcut(.return, modifiers: .command)
                Button(BrainDumpCopy.buttonLabel(model.store.dump)) { Task { await model.store.dumpButton() } }
                    .keyboardShortcut("b")
                    .disabled(model.call.state != .live)
                Divider()
                Button(MacCopy.openPage) { model.openPage() }.keyboardShortcut("p", modifiers: [.command, .shift])
            }
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    /// As the host of its own unit tests the app does nothing by itself: no daemon is looked for, no key is read, no
    /// status is asked. A test builds what it needs.
    static let hostsTests = ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard !Self.hostsTests else { return }
        AppModel.shared.launch()
    }

    /// Clicking the app in Finder or the Dock again opens the window: the menu bar item may be hidden behind a notch.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        AppModel.shared.windows.showMain()
        return true
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    /// Quitting ends the call cleanly, so a held prompt goes back to its terminal at once.
    func applicationWillTerminate(_ notification: Notification) {
        guard !Self.hostsTests else { return }
        AppModel.shared.call.hangUp()
    }
}

extension PointeStore {
    /// The one brain dump button: start, done, or back to the review.
    func dumpButton() async {
        guard let dump else { await dumpAction("start"); return }
        if dump.isDumping { await dumpAction("done") }
    }
}

/// The menu bar item: the small Chorus mark in the menu bar's one ink (dimmed with no call), and the state beside it:
/// a microphone while talking, the number of sessions that wait. Never colour alone, and the mark is never redrawn.
struct MenuBarLabel: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let state = model.store.menuBar
        HStack(spacing: 3) {
            Image(Self.image(state.kind))
            if state.kind == .talking { Image(systemName: "mic.fill") }
            if state.count > 0 { Text("\(state.count)").monospacedDigit() }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(state.accessibilityLabel)
        .help(state.title)
    }

    static func image(_ kind: MenuBarState.Kind) -> String {
        switch kind {
        case .down, .off: "MenuOff"
        case .live, .talking, .speaking, .needsYou: "MenuLive"
        }
    }
}

/// The menu: the state, the call, who needs you, and the ways in.
struct MenuContent: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        let store = model.store
        Text(store.menuBar.title)
        if let note = store.versionNote { Text(note.line) }
        Divider()
        Button(model.call.state == .off ? MacCopy.connect : MacCopy.hangUp) { Task { await model.toggleCall() } }
            .disabled(model.daemon == .node || model.daemon == .noPlugin || model.daemon == .squatter)
        if model.call.state == .live {
            Button(BrainDumpCopy.buttonLabel(store.dump)) {
                Task { await store.dumpButton() }
                model.windows.showMain()
            }
        }
        let pending = store.pending
        if !pending.isEmpty {
            Divider()
            ForEach(pending) { approval in
                Button("\(approval.label): \(MacCopy.tagApprove)…") { model.windows.showMain() }
            }
        }
        Divider()
        Button("Open Pointe") { model.windows.showMain() }.keyboardShortcut("o")
        Button(NewSessionCopy.title) { model.newSession() }.disabled(model.daemon != .running)
        Toggle("Show call bubble", isOn: Binding(get: { model.bubbleOn }, set: { model.bubbleOn = $0 }))
        Button("Settings…") {
            model.windows.activate()
            openSettings()
        }
        .keyboardShortcut(",")
        Divider()
        Button("Quit Pointe") { NSApp.terminate(nil) }.keyboardShortcut("q")
    }
}
