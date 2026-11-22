import AppKit
import Observation
import OSLog
import PointeKit
import PointeMacKit
import PointeUI

enum Log {
    static let subsystem = "io.ballerine.pointe.mac"
}

/// Where to reach the daemon, once the locator has checked that the listener is the daemon. Empty until then, and
/// emptied the moment a request cannot connect: the page key is never sent to a port that was not just verified.
final class EndpointBox: @unchecked Sendable {
    private let lock = NSLock()
    private var value: DaemonEndpoint?

    var endpoint: DaemonEndpoint? { lock.withLock { value } }
    func set(_ endpoint: DaemonEndpoint?) { lock.withLock { value = endpoint } }
}

/// The Mac app's shell: the daemon on this Mac (found, checked, started), and what belongs to this Mac alone (the
/// shortcut, the bubble, start at login, the keys' presence). The call and every screen are the shared module's
/// (`MacSession`, `PointeMacRoot`): the same ones the iPhone app draws (docs/design/parity.md).
@MainActor @Observable
final class AppModel {
    enum DaemonPhase: Equatable {
        case checking, noPlugin, node, stopped, squatter, starting, running
        case failed(String)
    }

    static let shared = AppModel()

    let session: MacSession
    let appVersion: String

    private(set) var daemon: DaemonPhase = .checking
    private(set) var plugin: PluginInstall?
    private(set) var keys: [Vendor: Bool] = [:]
    private(set) var keyNote: String?
    private(set) var setupID: String?
    private(set) var setupBusy = false
    private(set) var loginItem = false
    private(set) var loginNote: String?
    /// The shortcut arrived since Settings asked for it: proof that nothing else owns it.
    private(set) var shortcutSeen = false
    private(set) var shortcutNote: String?
    /// The folders a new session may start in (the daemon's setting, changed at the Mac only); nil until it answered.
    private(set) var folders: [String]?
    private(set) var foldersNote: String?

    var shortcut: Shortcut? { didSet { Shortcut.store(shortcut, in: defaults); registerShortcut() } }
    var bubbleOn: Bool { didSet { defaults.set(bubbleOn, forKey: Keys.bubble); windows.setBubble(bubbleOn) } }

    enum Keys {
        static let bubble = "pointe.bubble"
        static let opened = "pointe.opened"
    }

    let windows = Windows()
    private let defaults = UserDefaults.standard
    private let locator = DaemonLocator()
    private let box = EndpointBox()
    private let hotKey = HotKey()
    private var watcher: Task<Void, Never>?
    private var themeObserver: NSObjectProtocol?

    private init() {
        appVersion = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0"
        let box = box
        session = MacSession(daemon: LocalDaemon(endpoint: { box.endpoint }, lost: { box.set(nil) }))
        shortcut = Shortcut.stored(in: defaults)
        bubbleOn = defaults.bool(forKey: Keys.bubble)
        if session.isDemo { daemon = .running }  // a demo given at launch: nothing is looked for on this Mac
    }

    /// The call screen shows: Pointe runs on this Mac, or a demo is on. Otherwise the window is the setup guide.
    var ready: Bool { daemon == .running || session.isDemo || session.live }

    // MARK: launch

    func launch() {
        PointeBoot.start()
        applyTheme()
        themeObserver = NotificationCenter.default.addObserver(forName: UserDefaults.didChangeNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.applyTheme() }
        }
        let launchedForDemo = session.isDemo
        loginItem = !launchedForDemo && LoginItem.isOn
        session.alerts(isFront: { [windows] in windows.mainIsFront }, opened: { [windows] in windows.showMain() })
        hotKey.onDown = { [weak self] in self?.shortcutDown() }
        hotKey.onUp = { [weak self] in self?.session.talkUp() }
        registerShortcut()
        if !launchedForDemo {
            watcher = Task { [weak self] in await self?.watch() }
            session.start()
        }
        windows.setBubble(bubbleOn)
        // The window opens by itself the first time, and when a test or a screenshot asks.
        if UserDefaults.standard.bool(forKey: "PointeOpenWindow") || !defaults.bool(forKey: Keys.opened) {
            if !launchedForDemo { defaults.set(true, forKey: Keys.opened) }
            windows.showMain()
        }
    }

    // MARK: the daemon on this Mac

    /// While the daemon is not verified or does not answer: find it, check who listens, read the key again.
    private func watch() async {
        while !Task.isCancelled {
            if box.endpoint == nil || !session.reachable { await locate() }
            try? await Task.sleep(for: .seconds(box.endpoint == nil ? 2 : 1))
        }
    }

    func locate() async {
        let locator = locator
        let found = await Task.detached { locator.plugin() }.value
        if found != plugin { plugin = found }
        guard daemon != .starting else { return }
        do {
            box.set(try await locator.endpoint())
            set(.running)
        } catch LocatorError.node {
            box.set(nil); set(.node)
        } catch LocatorError.squatter {
            box.set(nil); set(.squatter)
        } catch {
            box.set(nil)
            if case .failed = daemon { return }  // keep the reason on screen until the next try
            set(plugin == nil ? .noPlugin : .stopped)
        }
    }

    private func set(_ phase: DaemonPhase) {
        if daemon != phase { daemon = phase }
    }

    /// Starts the daemon through the plugin's own `voice-daemon ensure`. The first run downloads, so this can take a while.
    func startDaemon() async {
        guard let plugin, daemon != .starting else { return }
        daemon = .starting
        do {
            try await locator.ensure(plugin)
            daemon = .checking
        } catch LocatorError.startFailed(let why) {
            daemon = .failed(why)
            return
        } catch {
            daemon = .failed(error.localizedDescription)
            return
        }
        await locate()
        await session.refresh()
    }

    func restartDaemon() async {
        guard let plugin, daemon != .starting else { return }
        session.hangUp()
        daemon = .starting
        box.set(nil)
        try? await locator.stop(plugin)
        daemon = .stopped
        await startDaemon()
    }

    var daemonLine: String {
        switch daemon {
        case .checking: "Looking for Pointe on this Mac…"
        case .noPlugin: MacCopy.noPlugin
        case .node: MacCopy.node
        case .stopped: MacCopy.daemonDown
        case .squatter: MacCopy.squatter
        case .starting: "Starting Pointe… the first start downloads about 180 MB."
        case .running: session.daemonVersion.map { "Running, version \($0)" } ?? "Running"
        case .failed(let why): why
        }
    }

    /// "Pointe on this Mac is 1.14.8; this app is 1.15.0", and how to bring the older side up; nil when they agree.
    var versionNote: (line: String, fix: String)? { VersionCheck.note(app: appVersion, daemon: session.daemonVersion) }

    var pageURL: URL { DaemonEndpoint(port: locator.paths.port, credential: .token("")).pageURL }

    /// The page, opened the way `bin/voice-open` does, so the browser has its own key.
    func openPage() {
        guard let plugin else { NSWorkspace.shared.open(pageURL); return }
        Task.detached {
            let process = Process()
            process.executableURL = plugin.root.appendingPathComponent("bin/voice-open")
            try? process.run()
        }
    }

    // MARK: keys (never read: only whether one is there)

    func refreshKeys() {
        guard !session.isDemo else { keys = [.gemini: true, .anthropic: true, .soniox: true, .elevenlabs: false, .openai: false]; setupID = "two"; return }
        setupID = locator.chosenSetup()
        Task {
            let found = await Task.detached { Dictionary(uniqueKeysWithValues: Vendor.allCases.map { ($0, KeychainPresence.has($0)) }) }.value
            keys = found
        }
    }

    /// Which roles the Keychain's keys fill under the chosen setup; nil until the first look.
    var keyPlan: KeyPlan? { keys.isEmpty ? nil : KeyPlan(present: Set(keys.filter(\.value).map(\.key)), setup: SetupChoice.named(setupID)) }

    /// After Add…, one tiny live call says whether the saved key works (`pointe key check`): the app never sees the key.
    func addKey(_ vendor: Vendor) async {
        guard let plugin else { keyNote = MacCopy.noPlugin; return }
        let saved = (try? await locator.addKey(vendor, plugin: plugin)) ?? "The key window did not open."
        refreshKeys()
        guard saved.hasPrefix("Saved") else { keyNote = saved; return }
        keyNote = "Saved. Checking it…"
        keyNote = (try? await locator.checkKey(vendor, plugin: plugin)) ?? saved
    }

    /// `pointe setup <id>`: the daemon uses exactly that setup's vendors after a restart.
    func chooseSetup(_ id: String) async {
        guard let plugin else { keyNote = MacCopy.noPlugin; return }
        setupBusy = true
        keyNote = (try? await locator.chooseSetup(id, plugin: plugin)) ?? "The setup could not be saved."
        setupBusy = false
        setupID = locator.chosenSetup()
        refreshKeys()
    }

    // MARK: where a new session may start

    func loadFolders() async {
        guard !session.isDemo else { folders = ["/Users/dana/work/shop"]; return }
        if let fresh = await session.sessionFolders() { folders = fresh }
    }

    func setFolders(_ paths: [String]) async {
        foldersNote = await session.setSessionFolders(paths)
        await loadFolders()
    }

    // MARK: the call

    func toggleCall() async {
        if !session.live, daemon == .stopped { await startDaemon() }
        await session.toggleCall()
    }

    /// From a menu or a key: the sheet is the window's, so the window comes first.
    func ask(_ command: MacSession.Command) {
        windows.showMain()
        session.ask(command)
    }

    func openMicrophoneSettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone") { NSWorkspace.shared.open(url) }
    }

    // MARK: the shortcut

    private func registerShortcut() {
        shortcutSeen = false
        guard let shortcut else { hotKey.register(nil); shortcutNote = nil; return }
        switch shortcut.problem {
        case .needsModifier:
            hotKey.register(nil)
            shortcutNote = "Add ⌃, ⌥ or ⌘: a key alone would be taken from every app."
        case .system(let owner):
            hotKey.register(nil)
            shortcutNote = "macOS uses \(shortcut.display) for \(owner). Choose another."
        case nil:
            shortcutNote = hotKey.register(shortcut) ? nil : "macOS refused \(shortcut.display). Choose another."
        }
    }

    /// From any app. On a call in push to talk it is the talk button; in Always on it mutes; with no call it brings
    /// Pointe forward, so the key always does something you can see.
    private func shortcutDown() {
        shortcutSeen = true
        if !session.talkDown() { windows.showMain() }
    }

    // MARK: this Mac's settings

    func setLoginItem(_ on: Bool) {
        loginNote = LoginItem.set(on)
        loginItem = LoginItem.isOn
    }

    /// The window's chrome follows Appearance (System, Light, Dark), which the shared Settings keeps in the defaults.
    private func applyTheme() {
        let wanted: NSAppearance? = switch defaults.string(forKey: PointeLook.themeKey) {
        case "light": NSAppearance(named: .aqua)
        case "dark": NSAppearance(named: .darkAqua)
        default: nil
        }
        if NSApp.appearance?.name != wanted?.name { NSApp.appearance = wanted }
    }
}
