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
    /// "Show the call bubble during calls": on a call, and with none when pinned (`BubbleRule.shows`). A demo keeps
    /// none of these.
    var bubbleOn: Bool { didSet { remember(bubbleOn, Keys.bubble); syncBubble() } }
    var bubblePinned: Bool { didSet { remember(bubblePinned, Keys.bubblePinned); syncBubble() } }
    /// The bubble as a small pill; hovering or clicking it shows the whole bubble (`bubbleExpanded`) until the mouse leaves.
    var bubbleSmall: Bool { didSet { remember(bubbleSmall, Keys.bubbleSmall); syncBubble() } }
    var bubbleExpanded = false { didSet { syncBubble() } }

    enum Keys {
        static let bubble = "pointe.bubble"
        static let bubblePinned = "pointe.bubble.pinned"
        static let bubbleSmall = "pointe.bubble.small"
    }

    let windows = Windows()
    private let defaults = UserDefaults.standard
    private let locator = DaemonLocator()
    private let box = EndpointBox()
    private let hotKey = HotKey()
    private var watcher: Task<Void, Never>?
    private var themeObserver: NSObjectProtocol?
    /// A call the person placed and that has not started yet: if it ends with a reason, the window opens on it.
    @ObservationIgnored private var dialing = false
    @ObservationIgnored private var launched = false

    private init() {
        appVersion = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0"
        let box = box
        session = MacSession(daemon: LocalDaemon(endpoint: { box.endpoint }, lost: { box.set(nil) }))
        shortcut = Shortcut.stored(in: defaults)
        bubbleOn = defaults.bool(forKey: Keys.bubble)
        bubblePinned = defaults.bool(forKey: Keys.bubblePinned)
        bubbleSmall = defaults.bool(forKey: Keys.bubbleSmall)
        if session.isDemo { daemon = .running }  // a demo given at launch: nothing is looked for on this Mac
    }

    /// Restart, from Settings: the daemon is down for a moment, by the person's own hand.
    private(set) var restarting = false

    /// The call screen shows: Pointe runs on this Mac (or is being restarted from here), or a demo is on. Otherwise the
    /// window is the setup guide. A restart that swapped in the whole checklist read as if setup had been lost.
    var ready: Bool { Self.showsCall(daemon: daemon, restarting: restarting, demo: session.isDemo, live: session.live) }

    static func showsCall(daemon: DaemonPhase, restarting: Bool, demo: Bool, live: Bool) -> Bool {
        daemon == .running || demo || live || (restarting && (daemon == .starting || daemon == .stopped || daemon == .checking))
    }

    // MARK: launch

    /// `openWindow`: the person opened the app (not macOS at login), so the window comes up: the menu bar item may be
    /// hidden behind the notch, and the bubble shows only on a call.
    func launch(openWindow: Bool) {
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
        launched = true
        watchCall()
        if openWindow || UserDefaults.standard.bool(forKey: "PointeOpenWindow") { windows.showMain() }
    }

    private func remember(_ value: Bool, _ key: String) {
        if !session.isDemo { defaults.set(value, forKey: key) }
    }

    /// The talk mode as the bubble and the window say it: "Always on", or "Hold ⌥Space" in push to talk.
    var talkMode: String {
        BubbleRule.talkMode(pushToTalk: session.pushToTalk, hold: session.holdToTalk, shortcut: shortcutNote == nil ? shortcut?.display : nil)
    }

    /// Keeps the bubble and the window in step with the call: the bubble shows or hides, and a call the person placed
    /// that ended with a reason opens the window on that reason.
    private func watchCall() {
        withObservationTracking {
            syncBubble()
            settleDial()
        } onChange: { [weak self] in
            Task { @MainActor in self?.watchCall() }
        }
    }

    /// At once on the person's own change, so the panel's size and its content change together.
    private func syncBubble() {
        guard launched else { return }
        windows.setBubble(BubbleRule.shows(on: bubbleOn, pinned: bubblePinned, phase: session.phase), small: bubbleSmall && !bubbleExpanded)
    }

    private func settleDial() {
        guard dialing, let failed = BubbleRule.failedDial(phase: session.phase, problem: session.callProblem) else { return }
        dialing = false
        if failed, !windows.mainIsFront { windows.showMain() }
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
        restarting = true
        defer { restarting = false }
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
        let locator = locator
        Task.detached { try? await locator.openPage(plugin) }  // through the runner: started disclaimed
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
        keyNote = "Paste the key in the window that opened. Pointe checks it, saves it and restarts."
        // `pointe key` checks the key with one tiny call, asks again when it is refused, and restarts Pointe on it.
        keyNote = (try? await locator.addKey(vendor, plugin: plugin)) ?? "The key window did not open."
        refreshKeys()
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

    /// From the bubble, the menu or ⌘↩. A call that does not start never fails silently: the window opens on Connect's
    /// reason and fix (`settleDial`).
    func toggleCall() async {
        dialing = session.phase == .off
        if !session.live, daemon == .stopped { await startDaemon() }
        await session.toggleCall()
        settleDial()
    }

    /// Settings or About while the window is the setup guide: it hosts them itself, as it has no call screen.
    var setupSheet: MacSetupSheet?

    /// From a menu or a key: the sheet is the window's, so the window comes first.
    func ask(_ command: MacSession.Command) {
        windows.showMain()
        if ready { session.ask(command) } else { setupSheet = MacSetupSheet(command) }
    }

    /// A sheet is over the main window (`Windows`): the menus' commands for the window wait until it closes.
    var sheetUp = false

    /// The setup guide has no call screen to open a sheet from: Settings and About open over the guide instead.
    static func setupAnswers(_ command: MacSession.Command) -> Bool { MacSetupSheet(command) != nil }

    func openMicrophoneSettings() {
        SystemSettings.openMicrophone()
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
