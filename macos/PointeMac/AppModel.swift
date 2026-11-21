import AppKit
import Observation
import OSLog
import PointeKit
import PointeMacKit

/// Where to reach the daemon, once the locator has checked that the listener is the daemon. Empty until then, and
/// emptied the moment a request cannot connect: the page key is never sent to a port that was not just verified.
final class EndpointBox: @unchecked Sendable {
    private let lock = NSLock()
    private var value: DaemonEndpoint?
    let session = DaemonEndpoint.session()

    var endpoint: DaemonEndpoint? { lock.withLock { value } }
    func set(_ endpoint: DaemonEndpoint?) { lock.withLock { value = endpoint } }
}

/// The daemon behind the box: every call goes to the endpoint verified last, or fails as "not reachable".
struct LiveDaemon: DaemonAPI {
    let box: EndpointBox

    private func run<T: Sendable>(_ work: (DaemonClient) async throws -> T) async throws -> T {
        guard let endpoint = box.endpoint else { throw URLError(.cannotConnectToHost) }
        do {
            return try await work(DaemonClient(endpoint: endpoint, session: box.session))
        } catch let failure as API.Failure {
            throw failure  // the daemon answered: it is there
        } catch {
            box.set(nil)   // nothing answered: whoever listens next is checked before it gets the key
            throw error
        }
    }

    func status() async throws -> API.Status { try await run { try await $0.status() } }
    func prefs() async throws -> API.Prefs { try await run { try await $0.prefs() } }
    func setPrefs(_ changes: [String: JSONValue]) async throws { try await run { try await $0.setPrefs(changes) } }
    func answer(session: String, requestId: String, allow: Bool, viaNotification: Bool) async throws {
        try await run { try await $0.answer(session: session, requestId: requestId, allow: allow, viaNotification: viaNotification) }
    }
    func switchTo(_ name: String) async throws { try await run { try await $0.switchTo(name) } }
    func disconnect(_ name: String) async throws { try await run { try await $0.disconnect(name) } }
    func say(_ text: String) async throws { try await run { try await $0.say(text) } }
    func correct(turn: Int, to text: String) async throws { try await run { try await $0.correct(turn: turn, to: text) } }
    func hungUp() async throws { try await run { try await $0.hungUp() } }
    func dump(_ action: String, text: String?, session: String?, to: String?) async throws {
        try await run { try await $0.dump(action, text: text, session: session, to: to) }
    }
    func voiceLock(level: String) async throws { try await run { try await $0.voiceLock(level: level) } }
    func talk(_ action: String) async throws { try await run { try await $0.talk(action) } }
    func dismissAttention(_ id: String) async throws { try await run { try await $0.dismissAttention(id) } }
}

/// Dials the endpoint in the box; with none, the dial fails as "never answered" and is tried again.
struct BoxDialer: CallDialer {
    let box: EndpointBox

    func dial() async throws -> any CallSocket {
        guard let endpoint = box.endpoint else { throw CallClose(code: 0) }
        return try await URLSessionCallDialer(request: { endpoint.callRequest }).dial()
    }
}

/// The app: the daemon on this Mac (found, checked, started), the call, the store the screens read, and what belongs
/// to this Mac alone (appearance, talk style, the shortcut, the bubble, alerts, start at login).
@MainActor @Observable
final class AppModel {
    enum DaemonPhase: Equatable {
        case checking, noPlugin, node, stopped, squatter, starting, running
        case failed(String)
    }

    static let shared = AppModel()

    let store: PointeStore
    let call: CallLink
    let appVersion: String
    /// A made-up daemon (launch argument `-PointeStub busy|empty`): for the UI tests and screenshots.
    let stub: StubDaemon?

    private(set) var daemon: DaemonPhase = .checking
    private(set) var plugin: PluginInstall?
    private(set) var keys: [Vendor: Bool] = [:]
    private(set) var keyNote: String?
    private(set) var loginItem = false
    private(set) var loginNote: String?
    /// The shortcut arrived since Settings asked for it: proof that nothing else owns it.
    private(set) var shortcutSeen = false
    private(set) var shortcutNote: String?
    private(set) var micDenied = false
    /// False while the call is up on audio that cannot cancel echo: the window says to use headphones.
    @ObservationIgnored private var echoCheck: @MainActor () -> Bool = { true }

    var theme: Theme { didSet { defaults.set(theme.rawValue, forKey: Theme.key); applyTheme() } }
    var talkStyle: TalkStyle { didSet { defaults.set(talkStyle.rawValue, forKey: TalkStyle.key); call.talkStyle = talkStyle } }
    var shortcut: Shortcut? { didSet { Shortcut.store(shortcut, in: defaults); registerShortcut() } }
    var bubbleOn: Bool { didSet { defaults.set(bubbleOn, forKey: Keys.bubble); windows.setBubble(bubbleOn) } }
    var alertsOn: Bool { didSet { defaults.set(alertsOn, forKey: Keys.alerts); alertsChanged() } }

    enum Keys {
        static let bubble = "pointe.bubble"
        static let alerts = "pointe.alerts"
        static let stubSuite = "io.ballerine.pointe.mac.stub"
    }

    let windows = Windows()
    private let defaults: UserDefaults
    private let locator = DaemonLocator()
    private let box = EndpointBox()
    private let hotKey = HotKey()
    private let notifier = Notifier()
    private var watcher: Task<Void, Never>?
    private let log = Logger(subsystem: Log.subsystem, category: "app")

    private init() {
        let arguments = UserDefaults.standard
        appVersion = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0"
        let words = CallLink.Words(notPaired: MacCopy.keyRefused, busy: MacCopy.busy, idleHangup: MacCopy.idleHangup,
                                   micDenied: MacCopy.micDenied, noMic: MacCopy.noMic, micFailed: MacCopy.micFailed,
                                   unreachable: { _ in MacCopy.daemonDown }, failed: MacCopy.failed)
        if let scenario = arguments.string(forKey: "PointeStub") {
            // The stub keeps its own settings, cleared at each launch, so a test never changes the real ones.
            UserDefaults.standard.removePersistentDomain(forName: Keys.stubSuite)
            defaults = UserDefaults(suiteName: Keys.stubSuite) ?? .standard
            var status = scenario == "empty" ? StubDaemon.empty(version: appVersion) : StubDaemon.busy(connected: false, version: appVersion)
            if let other = arguments.string(forKey: "PointeStubVersion") { status.version = other }
            let microphone = arguments.string(forKey: "PointeStubMic") == "ptt" ? "ptt" : "always"
            status.ptt = API.PTTStatus(mode: microphone, open: false)
            let daemon = StubDaemon(status: status, prefs: ["microphone": .string(microphone), "turns.patience": "normal"])
            stub = daemon
            call = CallLink(dialer: StubDialer(), audio: SilentAudio(), device: "Mac", place: MacCopy.thisMac, words: words,
                            hungUp: { try? await daemon.hungUp() })
            store = PointeStore(api: daemon, authenticator: FixedOwner(answer: arguments.string(forKey: "PointeStubOwner") != "no"),
                                appVersion: appVersion, call: call)
            self.daemon = .running
        } else {
            defaults = .standard
            stub = nil
            let live = LiveDaemon(box: box)
            let audio = MacAudio()
            call = CallLink(dialer: BoxDialer(box: box), audio: audio, device: "Mac", place: MacCopy.thisMac, words: words,
                            idleHangup: { try? await live.status().idle_hangup }, hungUp: { try? await live.hungUp() })
            store = PointeStore(api: live, authenticator: DeviceOwner(), appVersion: appVersion, call: call)
            audio.onLost = { [weak call, weak store] why in
                call?.hangUp()
                store?.notice = MacCopy.micFailed(why)
            }
            echoCheck = { [weak audio] in audio?.cancelsEcho ?? true }
        }
        theme = Theme.stored(defaults.string(forKey: Theme.key))
        talkStyle = TalkStyle.stored(in: defaults)
        shortcut = Shortcut.stored(in: defaults)
        bubbleOn = defaults.bool(forKey: Keys.bubble)
        alertsOn = defaults.bool(forKey: Keys.alerts)
        call.talkStyle = talkStyle
    }

    // MARK: launch

    func launch() {
        applyTheme()
        loginItem = stub == nil && LoginItem.isOn
        store.appIsFront = { [windows] in windows.mainIsFront }
        hotKey.onDown = { [weak self] in self?.shortcutDown() }
        hotKey.onUp = { [weak self] in self?.call.talkUp(.shortcut) }
        registerShortcut()
        if stub == nil {
            notifier.install()
            notifier.answer = { [store] in await store.answerFromNotification($0) }
            notifier.open = { [weak self] in self?.windows.showMain() }
            alertsChanged()
            watcher = Task { [weak self] in await self?.watch() }
        }
        store.start()
        windows.setBubble(bubbleOn)
        if stub != nil, UserDefaults.standard.bool(forKey: "PointeStubConnect") { Task { await toggleCall() } }
        // The window opens by itself the first time, when the daemon needs attention, and when a test asks.
        if UserDefaults.standard.bool(forKey: "PointeOpenWindow") || !defaults.bool(forKey: "pointe.opened") {
            defaults.set(true, forKey: "pointe.opened")
            windows.showMain()
        }
    }

    // MARK: the daemon on this Mac

    /// While the daemon is not verified or does not answer: find it, check who listens, read the key again.
    private func watch() async {
        while !Task.isCancelled {
            if box.endpoint == nil || store.reach != .ok { await locate() }
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
        await store.refresh()
    }

    func restartDaemon() async {
        guard let plugin, daemon != .starting else { return }
        call.hangUp()
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
        case .running: store.status?.version.map { "Running, version \($0)" } ?? "Running"
        case .failed(let why): why
        }
    }

    var pageURL: URL { DaemonEndpoint(port: locator.paths.port, credential: .token("")).pageURL }

    /// The page, for what the app leaves to it. Opened the way `bin/voice-open` does, so the browser has its own key.
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
        guard stub == nil else { keys = [.gemini: true, .anthropic: true, .soniox: true, .elevenlabs: false, .openai: false]; return }
        Task {
            let found = await Task.detached { Dictionary(uniqueKeysWithValues: Vendor.allCases.map { ($0, KeychainPresence.has($0)) }) }.value
            keys = found
        }
    }

    func addKey(_ vendor: Vendor) async {
        guard let plugin else { keyNote = MacCopy.noPlugin; return }
        keyNote = (try? await locator.addKey(vendor, plugin: plugin)) ?? "The key window did not open."
        refreshKeys()
    }

    // MARK: the call

    func toggleCall() async {
        switch call.state {
        case .off:
            if daemon == .stopped { await startDaemon() }
            await call.start()
            micDenied = call.problem == MacCopy.micDenied
            if call.state == .live, !echoCheck() { store.notice = MacCopy.noEchoCancelling }
        case .connecting, .live, .reconnecting:
            call.hangUp()
        }
        await store.refresh()
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
        guard call.state == .live else { windows.showMain(); return }
        if call.talk.ptt { call.talkDown(.shortcut) } else { call.toggleMute() }
    }

    // MARK: this Mac's settings

    func setLoginItem(_ on: Bool) {
        loginNote = LoginItem.set(on)
        loginItem = LoginItem.isOn
    }

    private func alertsChanged() {
        guard stub == nil else { return }
        store.alerts = notifier
        guard alertsOn else { store.alertsEnabled = false; return }
        Task {
            let allowed = await notifier.authorize()
            store.alertsEnabled = allowed
            if !allowed { alertsOn = false }
        }
    }

    private func applyTheme() {
        NSApp.appearance = switch theme {
        case .system: nil
        case .light: NSAppearance(named: .aqua)
        case .dark: NSAppearance(named: .darkAqua)
        }
    }
}
