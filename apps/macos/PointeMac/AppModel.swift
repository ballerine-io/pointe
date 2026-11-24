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

    var shortcut: Shortcut? { didSet { Shortcut.store(shortcut, in: defaults); registerShortcut(); registerSkipShortcut() } }
    /// The key that skips what Pointe is saying, from any app (docs/features/skip.md).
    var skipShortcut: Shortcut? { didSet { Shortcut.store(skipShortcut, .skip, in: defaults); registerSkipShortcut() } }
    private(set) var skipNote: String?
    /// "Show the call bubble during calls": on a call, and with none when pinned (`BubbleRule.shows`). A demo keeps
    /// none of these.
    var bubbleOn: Bool { didSet { remember(bubbleOn, Keys.bubble); syncBubble() } }
    /// Pinning a bubble that is switched off switches it on: nothing can be kept on screen that never shows.
    var bubblePinned: Bool {
        didSet {
            remember(bubblePinned, Keys.bubblePinned)
            if bubblePinned, !bubbleOn { bubbleOn = true } else { syncBubble() }
        }
    }
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
    private let hotKey = HotKey(id: 1)
    private let skipKey = HotKey(id: 2)
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
        skipShortcut = Shortcut.stored(.skip, in: defaults)
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
        skipKey.onDown = { [weak self] in self?.session.skip() }
        registerShortcut()
        registerSkipShortcut()
        if Self.preview != nil {
            showPreview()
        } else if !launchedForDemo {
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
        case .starting: MacCopy.starting
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

    // MARK: installing Pointe (install.sh, built into the app)

    struct InstallRun: Equatable {
        var fraction: Double
        var line: String
        var slow: Bool
    }

    private let installer = Installer()
    /// While install.sh runs: how far, and its last step in words.
    private(set) var installRun: InstallRun?
    private(set) var installProblem: String?

    /// A released app installs its own version, checked; a build between releases has no release to install.
    var canInstall: Bool { Self.preview != nil || (!session.isDemo && installer.canInstall(appVersion: appVersion)) }

    /// `-PointeSetupPreview fresh|installing|setup|key`, Debug builds only: the setup guide in that state, for
    /// screenshots and apps/macos/e2e/smoke.py. Nothing is looked for, installed, started or read from the Keychain.
    static var preview: String? {
        #if DEBUG
        UserDefaults.standard.string(forKey: "PointeSetupPreview")
        #else
        nil
        #endif
    }

    private func showPreview() {
        daemon = .noPlugin
        keys = Dictionary(uniqueKeysWithValues: Vendor.allCases.map { ($0, false) })
        switch Self.preview {
        case "installing":
            installRun = InstallRun(fraction: 0.42, line: "Installing Pointe's Python: about 180 MB the first time, under a minute on a fast connection…", slow: false)
        case "setup", "key":
            let root = FileManager.default.temporaryDirectory.appendingPathComponent("pointe-preview/\(appVersion)")
            try? FileManager.default.createDirectory(at: root.appendingPathComponent(".claude-plugin"), withIntermediateDirectories: true)
            try? FileManager.default.createDirectory(at: root.appendingPathComponent("bin"), withIntermediateDirectories: true)
            try? #"{"name": "pointe", "version": "\#(appVersion)"}"#.write(to: root.appendingPathComponent(".claude-plugin/plugin.json"), atomically: true, encoding: .utf8)
            FileManager.default.createFile(atPath: root.appendingPathComponent("bin/voice-daemon").path, contents: Data("#!/bin/sh\nexit 1\n".utf8), attributes: [.posixPermissions: 0o755])
            FileManager.default.createFile(atPath: root.appendingPathComponent(".pointe-install").path, contents: Data())
            plugin = PluginInstall(root: root)
            daemon = .stopped
            if Self.preview == "key" { setupID = "free" }
        default: break
        }
    }

    /// The standalone install is older than this app, which can bring it to its own version (`pointe update` still
    /// works too). The Claude Code plugin updates through Claude Code: the app never puts a second copy beside it.
    var canUpdate: Bool {
        guard let plugin, plugin.isStandalone, VersionCheck.compare(app: appVersion, daemon: plugin.version) == .daemonOlder else { return false }
        return canInstall
    }

    /// Installs Pointe, or updates the standalone install, with install.sh: the app's own version, checked against the
    /// SHA-256 pinned in the script, which is itself checked against the hash built into the app. install.sh restarts
    /// a Pointe that ran from the folder it replaces.
    func installPointe() async {
        guard Self.preview == nil, installRun == nil, plugin == nil || canUpdate else { return }
        installProblem = nil
        installRun = InstallRun(fraction: 0.01, line: "Starting…", slow: false)
        let creep = Task { [weak self] in  // the Python packages take a minute: the bar moves while they download
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                guard let self, var run = self.installRun, run.slow else { continue }
                run.fraction += (0.92 - run.fraction) * 0.04
                self.installRun = run
            }
        }
        defer { creep.cancel() }
        do {
            try await installer.install(appVersion: appVersion, environment: locator.scriptEnvironment()) { step in
                Task { @MainActor [weak self] in
                    guard let self, let run = self.installRun else { return }
                    self.installRun = InstallRun(fraction: max(run.fraction, step.fraction), line: step.line, slow: step.slow)
                }
            }
        } catch let problem as Installer.Problem {
            installProblem = problem.line
        } catch {
            installProblem = error.localizedDescription
        }
        installRun = nil
        await locate()
    }

    // MARK: uninstalling (pointe uninstall)

    /// Pointe → Uninstall Pointe…: `pointe uninstall`'s own list, one question (and the keys only on their own box),
    /// then `pointe uninstall --yes`. The app quits once its own copy is gone.
    func uninstallPointe() async {
        windows.activate()
        guard let plugin else {
            let alert = NSAlert()
            alert.messageText = "Pointe is not installed on this Mac."
            alert.informativeText = "To remove this app too, move it to the Trash."
            alert.runModal()
            return
        }
        let listed = (try? await locator.uninstall(plugin, ["--dry-run"]))?.output ?? ""
        let items = listed.split(separator: "\n").filter { $0.hasPrefix("  - ") }.map { "• " + $0.dropFirst(4) }
        let alert = NSAlert()
        alert.messageText = "Uninstall Pointe?"
        alert.informativeText = "This removes:\n\(items.joined(separator: "\n"))\n\nuv stays: other tools use it. The same as pointe uninstall in a terminal."
        let keys = NSButton(checkboxWithTitle: "Also delete Pointe's keys from the Keychain", target: nil, action: nil)
        alert.accessoryView = keys
        alert.addButton(withTitle: "Uninstall").hasDestructiveAction = true
        alert.addButton(withTitle: "Cancel")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        session.hangUp()
        let result = try? await locator.uninstall(plugin, ["--yes"] + (keys.state == .on ? ["--delete-keys"] : []))
        let done = NSAlert()
        done.messageText = result?.status == 0 ? "Pointe is removed." : "Some items were not removed."
        let failed = (result?.output ?? "").split(separator: "\n").filter { $0.contains("failed") }.joined(separator: "\n")
        done.informativeText = result.map { failed.isEmpty ? DaemonLocator.lastLines($0.output, 1) : failed } ?? "pointe uninstall did not run."
        done.runModal()
        if !FileManager.default.fileExists(atPath: Bundle.main.bundlePath) { NSApp.terminate(nil) }
        await locate()
    }

    // MARK: keys (never read: only whether one is there)

    func refreshKeys() {
        if Self.preview != nil { return }
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

    private func registerSkipShortcut() {
        skipNote = Self.skipProblem(skipShortcut, talk: shortcut)
        guard let skipShortcut, skipNote == nil else { skipKey.register(nil); return }
        if !skipKey.register(skipShortcut) { skipNote = "macOS refused \(skipShortcut.display). Choose another." }
    }

    /// Why a skip shortcut cannot be used, in Settings' words; nil when it can.
    static func skipProblem(_ skip: Shortcut?, talk: Shortcut?) -> String? {
        guard let skip else { return nil }
        if let clash = skip.clash(with: talk, .talk) { return clash }
        switch skip.problem {
        case .needsModifier: return "Add ⌃, ⌥ or ⌘: a key alone would be taken from every app."
        case .system(let owner): return "macOS uses \(skip.display) for \(owner). Choose another."
        case nil: return nil
        }
    }

    /// "Skip ⌃⌥S", as the bubble and the window say it beside the talk mode; nil with no working skip shortcut.
    var skipHint: String? { BubbleRule.skipHint(shortcut: skipNote == nil ? skipShortcut?.display : nil) }

    /// From any app. On a call in push to talk it is the talk button; in Always on it mutes; with no call it brings
    /// Pointe forward, so the key always does something you can see.
    private func shortcutDown() {
        shortcutSeen = true
        if !session.talkDown() { windows.showMain() }
    }

    // MARK: this Mac's settings

    func setLoginItem(_ on: Bool) {
        if session.isDemo { loginItem = on; return }  // a demo keeps nothing: the switch moves, this Mac's login items do not
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
