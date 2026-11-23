#if os(macOS)
import Foundation
import PointeKit

/// Where the daemon keeps its state and which port it listens on: the same two variables its scripts read.
public struct DaemonPaths: Sendable, Equatable {
    public let stateDir: URL
    public let port: Int

    public static let defaultPort = 7860

    public init(stateDir: URL, port: Int) {
        self.stateDir = stateDir
        self.port = port
    }

    public init(environment: [String: String], home: URL) {
        let state = environment["CLAUDE_VOICE_STATE"].flatMap { $0.isEmpty ? nil : $0 }
        stateDir = state.map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) } ?? home.appendingPathComponent(".claude-voice")
        port = environment["CLAUDE_VOICE_DAEMON_PORT"].flatMap(Int.init).flatMap { (1...65535).contains($0) ? $0 : nil } ?? Self.defaultPort
    }

    public var isDefault: Bool { port == Self.defaultPort && stateDir.lastPathComponent == ".claude-voice" }
    var pageKey: URL { stateDir.appendingPathComponent("page_key") }
    /// Written anew at each daemon start (`bin/voice-daemon`): a proof made for one start is refused by the next.
    var token: URL { stateDir.appendingPathComponent("token") }
    var pid: URL { stateDir.appendingPathComponent("daemon.pid") }
    var node: URL { stateDir.appendingPathComponent("node.json") }
    public var log: URL { stateDir.appendingPathComponent("daemon.log") }
}

/// An installed copy of Pointe (the Claude Code plugin, or the standalone install from install.sh): the folder with
/// `bin/voice-daemon`, and its version.
public struct PluginInstall: Sendable, Equatable {
    public let root: URL
    public let version: String

    var daemon: URL { root.appendingPathComponent("bin/voice-daemon") }
    var cli: URL { root.appendingPathComponent("bin/pointe") }

    /// A folder counts only if it is the Pointe plugin and can start the daemon.
    public init?(root: URL, files: FileManager = .default) {
        let manifest = root.appendingPathComponent(".claude-plugin/plugin.json")
        guard let data = try? Data(contentsOf: manifest),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              json["name"] as? String == "pointe", let version = json["version"] as? String,
              files.isExecutableFile(atPath: root.appendingPathComponent("bin/voice-daemon").path) else { return nil }
        self.root = root
        self.version = version
    }
}

public enum DaemonState: Equatable, Sendable {
    /// `node.json` names a hub: this machine has no call.
    case node
    case stopped
    /// Something listens on the port and it is not the daemon the pid file names: it gets nothing.
    case squatter
    case running(pid: Int32)
}

public enum LocatorError: Error, Equatable, Sendable {
    case node, stopped, squatter
    /// The key file is missing or empty: the daemon has not started yet.
    case noKey
    case noPlugin
    /// `voice-daemon ensure` failed: its last lines, which name the reason.
    case startFailed(String)
}

/// Finds the daemon on this Mac, checks that the listener is really it before any key is sent, and starts it through
/// the plugin's own script. It never reads a vendor key and never logs the page key.
public struct DaemonLocator: Sendable {
    public let paths: DaemonPaths
    private let home: URL
    private let environment: [String: String]
    private let runner: any CommandRunning

    public init(environment: [String: String] = ProcessInfo.processInfo.environment,
                home: URL = FileManager.default.homeDirectoryForCurrentUser, runner: any CommandRunning = ProcessRunner()) {
        self.environment = environment
        self.home = home
        self.runner = runner
        paths = DaemonPaths(environment: environment, home: home)
    }

    // MARK: is it there, and is it ours

    static let lsof = URL(fileURLWithPath: "/usr/sbin/lsof")
    static let pgrep = URL(fileURLWithPath: "/usr/bin/pgrep")

    static func pids(_ text: String) -> Set<Int32> {
        Set(text.split(whereSeparator: \.isNewline).compactMap { Int32($0.trimmingCharacters(in: .whitespaces)) })
    }

    func recordedPid() -> Int32? {
        guard let text = try? String(contentsOf: paths.pid, encoding: .utf8),
              let pid = Int32(text.trimmingCharacters(in: .whitespacesAndNewlines)), pid > 1 else { return nil }
        return pid
    }

    public var isNode: Bool {
        guard let data = try? Data(contentsOf: paths.node),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return false }
        return json["hub"] != nil
    }

    /// Who listens on the port, against the pid the daemon wrote: the listener must be that process or its child
    /// (`uv run` is the parent of the Python that listens), as `bin/voice-daemon` checks before it trusts the port.
    public func state() async -> DaemonState {
        if isNode { return .node }
        let listening = (try? await runner.run(Self.lsof, ["-nP", "-iTCP:\(paths.port)", "-sTCP:LISTEN", "-t"], environment: nil, timeout: 5))
            .map { Self.pids($0.output) } ?? []
        guard !listening.isEmpty else { return .stopped }
        guard let pid = recordedPid() else { return .squatter }
        var family: Set<Int32> = [pid]
        if let kids = try? await runner.run(Self.pgrep, ["-P", String(pid)], environment: nil, timeout: 5) {
            family.formUnion(Self.pids(kids.output))
        }
        return listening.isSubset(of: family) ? .running(pid: pid) : .squatter
    }

    /// The page's key and this daemon start's token, from the 0600 files the daemon wrote. In memory only: the caller
    /// must not log or store them, and neither is ever sent (`LocalProof`).
    func secret(_ file: URL) throws -> String {
        guard let value = try? String(contentsOf: file, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty else { throw LocatorError.noKey }
        return value
    }

    /// Where to connect, once the listener is known to be the daemon. Throws rather than talk to anything else.
    public func endpoint() async throws -> DaemonEndpoint {
        switch await state() {
        case .node: throw LocatorError.node
        case .stopped: throw LocatorError.stopped
        case .squatter: throw LocatorError.squatter
        case .running: return DaemonEndpoint(port: paths.port, credential: .pageKey(try secret(paths.pageKey), token: try secret(paths.token)))
        }
    }

    // MARK: the installed plugin

    /// Claude Code's folders: `CLAUDE_CONFIG_DIR` when set, then `~/.claude`.
    var configDirs: [URL] {
        var dirs: [URL] = []
        if let custom = environment["CLAUDE_CONFIG_DIR"], !custom.isEmpty { dirs.append(URL(fileURLWithPath: (custom as NSString).expandingTildeInPath)) }
        dirs.append(home.appendingPathComponent(".claude"))
        return dirs
    }

    /// A folder the user chose; otherwise the newer of the Claude Code plugin and the standalone install, the standalone
    /// one on a tie, as `bin/pointe-installs` picks. A candidate that is not Pointe is skipped.
    public func plugin(chosen: URL? = nil) -> PluginInstall? {
        if let chosen, let install = PluginInstall(root: chosen) { return install }
        return [standalone(), claudePlugin()].compactMap { $0 }
            .max(by: { VersionCheck.compare(app: $0.version, daemon: $1.version) == .appOlder })
    }

    /// install.sh's folders: `$POINTE_HOME` (else `~/.pointe`)/<version>, each with the `.pointe-install` file written
    /// once its SHA-256 matched. The newest.
    func standalone() -> PluginInstall? {
        let base = environment["POINTE_HOME"].flatMap { $0.isEmpty ? nil : URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) }
            ?? home.appendingPathComponent(".pointe")
        let folders = (try? FileManager.default.contentsOfDirectory(at: base, includingPropertiesForKeys: nil)) ?? []
        return folders.filter { FileManager.default.fileExists(atPath: $0.appendingPathComponent(".pointe-install").path) }
            .compactMap { PluginInstall(root: $0) }
            .max(by: { VersionCheck.compare(app: $0.version, daemon: $1.version) == .appOlder })
    }

    /// The install path Claude Code recorded for `pointe@pointe`; else the newest version in its plugin cache.
    func claudePlugin() -> PluginInstall? {
        for dir in configDirs {
            let record = dir.appendingPathComponent("plugins/installed_plugins.json")
            if let data = try? Data(contentsOf: record),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let plugins = json["plugins"] as? [String: Any], let entries = plugins["pointe@pointe"] as? [[String: Any]] {
                for entry in entries {
                    if let path = entry["installPath"] as? String, let install = PluginInstall(root: URL(fileURLWithPath: path)) { return install }
                }
            }
            let cache = dir.appendingPathComponent("plugins/cache/pointe/pointe")
            let versions = (try? FileManager.default.contentsOfDirectory(at: cache, includingPropertiesForKeys: nil)) ?? []
            let installs = versions.compactMap { PluginInstall(root: $0) }
            if let newest = installs.max(by: { VersionCheck.compare(app: $0.version, daemon: $1.version) == .appOlder }) { return newest }
        }
        return nil
    }

    /// What the plugin's scripts need that a GUI app's environment lacks: `uv` in `~/.local/bin` or Homebrew, and the
    /// state and port when they are not the defaults. Nothing else is added, and no key is passed: the daemon reads its
    /// own from the Keychain.
    func scriptEnvironment() -> [String: String] {
        var env: [String: String] = [:]
        for name in ["HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "SHELL", "CLAUDE_VOICE_STATE", "CLAUDE_VOICE_DAEMON_PORT"] {
            if let value = environment[name] { env[name] = value }
        }
        env["HOME"] = env["HOME"] ?? home.path
        let extra = ["\(home.path)/.local/bin", "/opt/homebrew/bin", "/usr/local/bin"]
        let base = environment["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin"
        env["PATH"] = (base.split(separator: ":").map(String.init) + extra.filter { !base.contains($0) }).joined(separator: ":")
        return env
    }

    /// Starts the daemon if it is not running: the plugin's own `voice-daemon ensure`, unchanged. The first run
    /// downloads its dependencies, so this can take minutes.
    public func ensure(_ plugin: PluginInstall) async throws {
        let result = try await runner.run(plugin.daemon, ["ensure"], environment: scriptEnvironment(), timeout: 600)
        guard result.status == 0 else { throw LocatorError.startFailed(Self.lastLines(result.errors.isEmpty ? result.output : result.errors)) }
    }

    /// The page in the browser, as `bin/voice-open` opens it: the browser then holds its own key.
    public func openPage(_ plugin: PluginInstall) async throws {
        _ = try await runner.run(plugin.root.appendingPathComponent("bin/voice-open"), [], environment: scriptEnvironment(), timeout: 30)
    }

    public func stop(_ plugin: PluginInstall) async throws {
        _ = try await runner.run(plugin.daemon, ["stop"], environment: scriptEnvironment(), timeout: 60)
    }

    /// `pointe key <vendor>`: the plugin's hidden-input dialog, which stores the key through `security`'s own prompt.
    /// The key never passes through this app. Returns the script's one line ("Saved…", "Cancelled…").
    public func addKey(_ vendor: Vendor, plugin: PluginInstall) async throws -> String {
        let result = try await runner.run(plugin.cli, ["key", vendor.rawValue], environment: scriptEnvironment(), timeout: 300)
        return Self.lastLines(result.output, 1)
    }

    /// `pointe key check <vendor>`: one tiny live call with the saved key. Returns its one line ("The gemini key works.").
    public func checkKey(_ vendor: Vendor, plugin: PluginInstall) async throws -> String {
        let result = try await runner.run(plugin.cli, ["key", "check", vendor.rawValue], environment: scriptEnvironment(), timeout: 60)
        return Self.lastLines(result.output, 1)
    }

    /// `pointe setup <id>`: from now on the daemon uses exactly that setup's vendors. The local setups download their
    /// models first, so this can take minutes.
    public func chooseSetup(_ id: String, plugin: PluginInstall) async throws -> String {
        let result = try await runner.run(plugin.cli, ["setup", id], environment: scriptEnvironment(), timeout: 1200)
        return Self.lastLines(result.output, 2)
    }

    /// The setup in config.json ("setup"), nil when none was chosen. The file holds no secret.
    public func chosenSetup() -> String? {
        guard let data = try? Data(contentsOf: paths.stateDir.appendingPathComponent("config.json")),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return json["setup"] as? String
    }

    static func lastLines(_ text: String, _ n: Int = 4) -> String {
        text.split(whereSeparator: \.isNewline).map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
            .suffix(n).joined(separator: "\n")
    }
}

/// The model vendors a key can be stored for, and each one's Keychain item: `vendors.KEYS`, held to it by
/// tests/test_macos_parity.py.
public enum Vendor: String, CaseIterable, Identifiable, Sendable {
    case gemini, openai, anthropic, soniox, elevenlabs

    public var id: String { rawValue }
    public var service: String { "pointe.\(rawValue)-api-key" }
    /// The item's name before 1.20.0 (`vendors.LEGACY_ITEMS`): still read, never written.
    public var legacyService: String { "\(rawValue)-api-key" }
    public var label: String {
        switch self {
        case .gemini: "Google Gemini"
        case .openai: "OpenAI"
        case .anthropic: "Anthropic"
        case .soniox: "Soniox"
        case .elevenlabs: "ElevenLabs"
        }
    }
}
#endif
