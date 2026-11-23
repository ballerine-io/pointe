import AppKit
import PointeKit
import PointeUI
import SwiftUI

/// Pointe for the Mac: a menu bar item and a window for the call. The window draws the screens the iPhone app draws
/// (the shared module, docs/design/parity.md); this target is the Mac's shell around them: the menu bar item, the menus
/// and their keys, the call bubble, the talk shortcut, start at login, and finding and starting Pointe on this Mac.
/// With no window open it has no Dock icon.
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
        .commands { PointeCommands(model: model) }
    }
}

/// The menu bar's menus: every main action has a key (docs/design/parity.md, "Keys").
struct PointeCommands: Commands {
    let model: AppModel

    var body: some Commands {
        CommandGroup(replacing: .appInfo) {
            Button("About Pointe") { model.ask(.about) }
        }
        CommandGroup(replacing: .appSettings) {
            Button("Settings…") { model.ask(.settings) }.keyboardShortcut(",")
        }
        CommandGroup(replacing: .newItem) {
            Button("Open Pointe") { model.windows.showMain() }.keyboardShortcut("o")
            Button(MacMenu.newSession) { model.ask(.newSession) }.keyboardShortcut("n")
                .disabled(!model.ready)
            Button(MacMenu.addSessions) { model.ask(.addSessions) }.keyboardShortcut("j", modifiers: [.command, .shift])
                .disabled(!model.ready)
        }
        CommandMenu("Call") {
            Button(model.session.phase == .off ? MacCopy.connect : MacCopy.hangUp) { Task { await model.toggleCall() } }
                .keyboardShortcut(.return, modifiers: .command)
                .disabled(model.session.isDemo)
            Button(model.session.dumpLabel) { model.ask(.brainDump) }
                .keyboardShortcut("b")
                .disabled(!model.session.live)
            Button(MacMenu.type) { model.ask(.type) }.keyboardShortcut("t").disabled(!model.ready)
            Divider()
            Button(MacMenu.sessions) { model.ask(.sessions) }.keyboardShortcut("s", modifiers: [.command, .shift]).disabled(!model.ready)
            Button(MacMenu.meeting) { model.ask(.meeting) }.keyboardShortcut("m", modifiers: [.command, .shift]).disabled(!model.ready)
            Button(MacMenu.briefing) { model.ask(.briefing) }.keyboardShortcut("b", modifiers: [.command, .shift]).disabled(!model.ready)
            Button(MacMenu.nightShift) { model.ask(.nightShift) }.keyboardShortcut("n", modifiers: [.command, .shift]).disabled(!model.ready)
            Button(MacMenu.machines) { model.ask(.machines) }.disabled(!model.ready)
            Button(MacMenu.phone) { model.ask(.phone) }.disabled(!model.ready || model.session.isDemo)
            Divider()
            Button(MacCopy.openPage) { model.openPage() }.keyboardShortcut("p", modifiers: [.command, .shift])
                .disabled(model.daemon != .running)
        }
    }
}

/// The menus' own words: each names the sheet it opens by that sheet's title.
enum MacMenu {
    static let newSession = "New Session"
    static let addSessions = "Add Sessions"
    static let type = "Type Instead of Talking"
    static let sessions = "Sessions and Mode"
    static let meeting = "Start a Meeting"
    static let briefing = "Briefing"
    static let nightShift = NightShiftCopy.title
    static let machines = "Machines"
    static let phone = "Pair a Phone…"
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    /// As the host of its own unit tests the app does nothing by itself: no daemon is looked for, no key is read, no
    /// status is asked. A test builds what it needs.
    static let hostsTests = ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard !Self.hostsTests else { return }
        AppModel.shared.launch(openWindow: Self.opensWindow(asLoginItem: Self.launchedAsLoginItem))
    }

    /// A launch the person made opens the window, so the app is always in reach: the menu bar item can sit behind the
    /// notch, and the bubble shows only on a call. A launch at login stays in the menu bar.
    static func opensWindow(asLoginItem: Bool) -> Bool { !asLoginItem }

    /// macOS marks the open-application event of a login item's launch.
    static var launchedAsLoginItem: Bool {
        guard let event = NSAppleEventManager.shared().currentAppleEvent, event.eventID == kAEOpenApplication else { return false }
        return event.paramDescriptor(forKeyword: keyAEPropData)?.enumCodeValue == keyAELaunchedAsLogInItem
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
        AppModel.shared.session.hangUp()
    }
}

/// The menu bar item: the small Chorus mark in the menu bar's one ink (dimmed with no call), and the state beside it:
/// a microphone while talking, the number of sessions that wait. Never colour alone, and the mark is never redrawn.
struct MenuBarLabel: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let session = model.session
        let glyph = session.glyph
        HStack(spacing: 3) {
            Image(Self.image(glyph))
            if glyph == .talking { Image(systemName: "mic.fill") }
            if glyph == .needsYou { Text("\(session.needCount)").monospacedDigit() }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(MacCopy.appName): \(session.menuTitle)")
        .help(session.menuTitle)
    }

    static func image(_ glyph: MacSession.Glyph) -> String {
        switch glyph {
        case .down, .off: "MenuOff"
        case .live, .talking, .speaking, .needsYou: "MenuLive"
        }
    }
}

/// The menu: the state, the call, who needs you, and the ways in.
struct MenuContent: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let session = model.session
        Text(session.menuTitle)
        if let note = model.versionNote { Text(note.line) }
        Divider()
        Button(session.phase == .off ? MacCopy.connect : MacCopy.hangUp) { Task { await model.toggleCall() } }
            .disabled(model.daemon == .node || model.daemon == .noPlugin || model.daemon == .squatter || session.isDemo)
        if session.live {
            Button(session.dumpLabel) { model.ask(.brainDump) }
        }
        let waiting = session.waiting
        if !waiting.isEmpty {
            Divider()
            ForEach(waiting) { item in
                Button("\(item.label): \(MacCopy.tagApprove)…") { model.windows.showMain() }
            }
        }
        Divider()
        Button("Open Pointe") { model.windows.showMain() }.keyboardShortcut("o")
        Button(MacMenu.newSession) { model.ask(.newSession) }.disabled(!model.ready)
        Toggle("Show call bubble during calls", isOn: Binding(get: { model.bubbleOn }, set: { model.bubbleOn = $0 }))
        Button("Settings…") { model.ask(.settings) }.keyboardShortcut(",")
        Divider()
        Button("Quit Pointe") { NSApp.terminate(nil) }.keyboardShortcut("q")
    }
}
