#if os(macOS)
import Foundation
import PointeKit
import Testing
@testable import PointeMacKit

/// Answers `lsof` and `pgrep` from a table and records everything else it was asked to run.
final class FakeRunner: CommandRunning, @unchecked Sendable {
    private let lock = NSLock()
    private var log: [(URL, [String], [String: String]?)] = []
    var listening = "", children = "", script = CommandResult(status: 0, output: "http://127.0.0.1:7999\n")

    var ran: [(URL, [String], [String: String]?)] { lock.withLock { log } }

    func run(_ executable: URL, _ arguments: [String], environment: [String: String]?, timeout: TimeInterval) async throws -> CommandResult {
        lock.withLock { log.append((executable, arguments, environment)) }
        switch executable.lastPathComponent {
        case "lsof": return CommandResult(status: listening.isEmpty ? 1 : 0, output: listening)
        case "pgrep": return CommandResult(status: children.isEmpty ? 1 : 0, output: children)
        default: return script
        }
    }
}

struct Sandbox {
    let home: URL
    var state: URL { home.appendingPathComponent(".claude-voice") }

    init() throws {
        home = FileManager.default.temporaryDirectory.appendingPathComponent("pointe-locator-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: home.appendingPathComponent(".claude-voice"), withIntermediateDirectories: true)
    }

    func write(_ text: String, to path: String) throws {
        let url = home.appendingPathComponent(path)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try text.write(to: url, atomically: true, encoding: .utf8)
    }

    /// A folder that looks like the installed plugin: the manifest and an executable `bin/voice-daemon`.
    @discardableResult func plugin(_ path: String, version: String, name: String = "pointe") throws -> URL {
        try write(#"{"name": "\#(name)", "version": "\#(version)"}"#, to: "\(path)/.claude-plugin/plugin.json")
        try write("#!/bin/sh\n", to: "\(path)/bin/voice-daemon")
        let root = home.appendingPathComponent(path)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: root.appendingPathComponent("bin/voice-daemon").path)
        return root
    }

    func locator(_ runner: FakeRunner, environment: [String: String] = [:]) -> DaemonLocator {
        DaemonLocator(environment: environment, home: home, runner: runner)
    }

    func remove() { try? FileManager.default.removeItem(at: home) }
}

@Suite struct PathTests {
    let home = URL(fileURLWithPath: "/Users/mira")

    @Test func theDefaultsAreTheDaemons() {
        let paths = DaemonPaths(environment: [:], home: home)
        #expect(paths.stateDir.path == "/Users/mira/.claude-voice" && paths.port == 7860 && paths.isDefault)
    }

    @Test func theScriptsVariablesMoveBoth() {
        let paths = DaemonPaths(environment: ["CLAUDE_VOICE_STATE": "/tmp/cv-state", "CLAUDE_VOICE_DAEMON_PORT": "7999"], home: home)
        #expect(paths.stateDir.path == "/tmp/cv-state" && paths.port == 7999 && !paths.isDefault)
        #expect(DaemonPaths(environment: ["CLAUDE_VOICE_DAEMON_PORT": "seven"], home: home).port == 7860)
        #expect(DaemonPaths(environment: ["CLAUDE_VOICE_DAEMON_PORT": "70000"], home: home).port == 7860)
    }
}

@Suite struct ListenerTests {
    @Test func nothingListeningIsStopped() async throws {
        let box = try Sandbox(); defer { box.remove() }
        #expect(await box.locator(FakeRunner()).state() == .stopped)
    }

    @Test func theRecordedProcessOrItsChildIsOurs() async throws {
        let box = try Sandbox(); defer { box.remove() }
        try box.write("4100\n", to: ".claude-voice/daemon.pid")
        let runner = FakeRunner()
        runner.listening = "4100\n"
        #expect(await box.locator(runner).state() == .running(pid: 4100))
        runner.listening = "4177\n"; runner.children = "4177\n"  // uv run is the parent of the Python that listens
        #expect(await box.locator(runner).state() == .running(pid: 4100))
    }

    @Test func anotherProgramOnThePortGetsNothing() async throws {
        let box = try Sandbox(); defer { box.remove() }
        try box.write("4100\n", to: ".claude-voice/daemon.pid")
        try box.write("the-page-key", to: ".claude-voice/page_key")
        let runner = FakeRunner()
        runner.listening = "999\n"
        #expect(await box.locator(runner).state() == .squatter)
        await #expect(throws: LocatorError.squatter) { try await box.locator(runner).endpoint() }
    }

    @Test func aListenerWithNoPidFileIsNotTrusted() async throws {
        let box = try Sandbox(); defer { box.remove() }
        let runner = FakeRunner()
        runner.listening = "4100\n"
        #expect(await box.locator(runner).state() == .squatter)
    }

    @Test func theKeyIsHandedOnlyToTheVerifiedDaemonAndOnLoopback() async throws {
        let box = try Sandbox(); defer { box.remove() }
        try box.write("4100", to: ".claude-voice/daemon.pid")
        try box.write("the-page-key\n", to: ".claude-voice/page_key")
        try box.write("this-starts-token\n", to: ".claude-voice/token")
        let runner = FakeRunner()
        runner.listening = "4100\n"
        let endpoint = try await box.locator(runner, environment: ["CLAUDE_VOICE_DAEMON_PORT": "7999"]).endpoint()
        #expect(endpoint == DaemonEndpoint(port: 7999, credential: .pageKey("the-page-key", token: "this-starts-token")))
        #expect(endpoint.base.host == "127.0.0.1")
    }

    @Test func aDaemonThatHasNotWrittenItsKeyYetSaysSo() async throws {
        let box = try Sandbox(); defer { box.remove() }
        try box.write("4100", to: ".claude-voice/daemon.pid")
        let runner = FakeRunner()
        runner.listening = "4100\n"
        await #expect(throws: LocatorError.noKey) { try await box.locator(runner).endpoint() }
        try box.write("  \n", to: ".claude-voice/page_key")
        await #expect(throws: LocatorError.noKey) { try await box.locator(runner).endpoint() }
        try box.write("the-page-key\n", to: ".claude-voice/page_key")  // a key, and no token of this start: no proof
        await #expect(throws: LocatorError.noKey) { try await box.locator(runner).endpoint() }
    }

    @Test func aNodeHasNoCall() async throws {
        let box = try Sandbox(); defer { box.remove() }
        try box.write(#"{"hub": {"name": "studio"}}"#, to: ".claude-voice/node.json")
        #expect(await box.locator(FakeRunner()).state() == .node)
        await #expect(throws: LocatorError.node) { try await box.locator(FakeRunner()).endpoint() }
    }
}

@Suite struct PluginTests {
    @Test func theRecordedInstallPathWins() async throws {
        let box = try Sandbox(); defer { box.remove() }
        let recorded = try box.plugin(".claude/plugins/cache/pointe/pointe/1.14.8", version: "1.14.8")
        try box.plugin(".claude/plugins/cache/pointe/pointe/1.15.0", version: "1.15.0")
        try box.write(#"{"plugins": {"pointe@pointe": [{"installPath": "\#(recorded.path)", "version": "1.14.8"}]}}"#,
                      to: ".claude/plugins/installed_plugins.json")
        #expect(box.locator(FakeRunner()).plugin()?.version == "1.14.8")
    }

    @Test func withoutARecordTheNewestCachedVersionIsUsed() async throws {
        let box = try Sandbox(); defer { box.remove() }
        try box.plugin(".claude/plugins/cache/pointe/pointe/1.9.0", version: "1.9.0")
        try box.plugin(".claude/plugins/cache/pointe/pointe/1.14.8", version: "1.14.8")
        try box.plugin(".claude/plugins/cache/pointe/pointe/1.10.2", version: "1.10.2")
        #expect(box.locator(FakeRunner()).plugin()?.version == "1.14.8")
    }

    @Test func aFolderThatIsNotThePluginIsSkipped() async throws {
        let box = try Sandbox(); defer { box.remove() }
        try box.plugin(".claude/plugins/cache/pointe/pointe/9.9.9", version: "9.9.9", name: "something-else")
        try box.write(#"{"name": "pointe", "version": "2.0.0"}"#, to: ".claude/plugins/cache/pointe/pointe/2.0.0/.claude-plugin/plugin.json")  // no bin/
        #expect(box.locator(FakeRunner()).plugin() == nil)
    }

    @Test func theNewerOfThePluginAndTheStandaloneInstallWinsAndTheStandaloneOneOnATie() async throws {
        let box = try Sandbox(); defer { box.remove() }
        try box.plugin(".claude/plugins/cache/pointe/pointe/1.23.0", version: "1.23.0")
        try box.plugin(".pointe/1.24.0", version: "1.24.0")
        try box.write("standalone 1.24.0\n", to: ".pointe/1.24.0/.pointe-install")
        try box.plugin(".pointe/1.99.0", version: "1.99.0")  // no .pointe-install: install.sh never finished it
        #expect(box.locator(FakeRunner()).plugin()?.root.lastPathComponent == "1.24.0")
        #expect(box.locator(FakeRunner()).plugin()?.root.deletingLastPathComponent().lastPathComponent == ".pointe")
        try box.plugin(".claude/plugins/cache/pointe/pointe/1.25.0", version: "1.25.0")
        #expect(box.locator(FakeRunner()).plugin()?.version == "1.25.0")
        try box.plugin(".pointe/1.25.0", version: "1.25.0")
        try box.write("standalone 1.25.0\n", to: ".pointe/1.25.0/.pointe-install")
        #expect(box.locator(FakeRunner()).plugin()?.root.deletingLastPathComponent().lastPathComponent == ".pointe")
    }

    @Test func aChosenFolderAndClaudesConfigDirAreHonoured() async throws {
        let box = try Sandbox(); defer { box.remove() }
        let chosen = try box.plugin("src/pointe", version: "1.15.0")
        #expect(box.locator(FakeRunner()).plugin(chosen: chosen)?.root == chosen)
        try box.plugin("work/plugins/cache/pointe/pointe/1.14.0", version: "1.14.0")
        let custom = box.locator(FakeRunner(), environment: ["CLAUDE_CONFIG_DIR": box.home.appendingPathComponent("work").path])
        #expect(custom.plugin()?.version == "1.14.0")
    }

    @Test func startingRunsThePluginsOwnScriptWithNoSecretInItsEnvironment() async throws {
        let box = try Sandbox(); defer { box.remove() }
        let root = try box.plugin("src/pointe", version: "1.15.0")
        let plugin = try #require(PluginInstall(root: root))
        let runner = FakeRunner()
        let env = ["CLAUDE_VOICE_STATE": "/tmp/cv-state", "CLAUDE_VOICE_DAEMON_PORT": "7999", "ANTHROPIC_API_KEY": "sk-made-up",
                   "PATH": "/usr/bin:/bin", "HOME": box.home.path]
        try await box.locator(runner, environment: env).ensure(plugin)
        let (executable, arguments, passed) = try #require(runner.ran.last)
        #expect(executable.path.hasSuffix("src/pointe/bin/voice-daemon") && arguments == ["ensure"])
        let sent = try #require(passed)
        #expect(sent["CLAUDE_VOICE_STATE"] == "/tmp/cv-state" && sent["CLAUDE_VOICE_DAEMON_PORT"] == "7999")
        #expect(sent["ANTHROPIC_API_KEY"] == nil)
        #expect(sent["PATH"]?.contains("/.local/bin") == true && sent["PATH"]?.contains("/opt/homebrew/bin") == true)
    }

    @Test func aStartThatFailsSaysTheScriptsLastLines() async throws {
        let box = try Sandbox(); defer { box.remove() }
        let plugin = try #require(PluginInstall(root: try box.plugin("src/pointe", version: "1.15.0")))
        let runner = FakeRunner()
        runner.script = CommandResult(status: 1, errors: "\nvoice-daemon: uv is missing. Install it: https://docs.astral.sh/uv/\n")
        await #expect(throws: LocatorError.startFailed("voice-daemon: uv is missing. Install it: https://docs.astral.sh/uv/")) {
            try await box.locator(runner).ensure(plugin)
        }
    }

    @Test func addingAKeyRunsThePluginsDialogAndNeverSeesTheKey() async throws {
        let box = try Sandbox(); defer { box.remove() }
        let plugin = try #require(PluginInstall(root: try box.plugin("src/pointe", version: "1.15.0")))
        let runner = FakeRunner()
        runner.script = CommandResult(status: 0, output: "Saved your soniox key in the Keychain as soniox-api-key.\n")
        let said = try await box.locator(runner).addKey(.soniox, plugin: plugin)
        #expect(said.hasPrefix("Saved your soniox key"))
        #expect(runner.ran.last?.1 == ["key", "soniox"])
    }

    /// Every script of the plugin goes through the runner, which starts it disclaimed (CommandRunnerTests).
    @Test func openingThePageRunsThePluginsOwnScriptThroughTheRunner() async throws {
        let box = try Sandbox(); defer { box.remove() }
        let plugin = try #require(PluginInstall(root: try box.plugin("src/pointe", version: "1.15.0")))
        let runner = FakeRunner()
        try await box.locator(runner, environment: ["ANTHROPIC_API_KEY": "sk-made-up", "HOME": box.home.path]).openPage(plugin)
        let (executable, arguments, passed) = try #require(runner.ran.last)
        #expect(executable.path.hasSuffix("src/pointe/bin/voice-open") && arguments.isEmpty)
        #expect(passed?["ANTHROPIC_API_KEY"] == nil && passed?["HOME"] == box.home.path)
    }

    @Test func eachVendorsKeychainItemIsTheDaemons() {
        #expect(Vendor.allCases.map(\.service) == ["pointe.gemini-api-key", "pointe.openai-api-key", "pointe.anthropic-api-key", "pointe.soniox-api-key", "pointe.elevenlabs-api-key"])
        #expect(Vendor.allCases.map(\.legacyService) == ["gemini-api-key", "openai-api-key", "anthropic-api-key", "soniox-api-key", "elevenlabs-api-key"])
    }
}
#endif

#if os(macOS)
@Suite struct ShortcutTests {
    @Test func theDefaultIsControlOptionSpace() {
        #expect(Shortcut.standard.display == "⌃⌥Space" && Shortcut.standard.spoken == "Control Option Space")
        #expect(Shortcut.standard.problem == nil)
    }

    @Test func aKeyAloneWouldSwallowTypingButAFunctionKeyMay() {
        #expect(Shortcut(keyCode: 0, modifiers: 0).problem == .needsModifier)
        #expect(Shortcut(keyCode: 0, modifiers: Shortcut.shift).problem == .needsModifier)
        #expect(Shortcut(keyCode: 96, modifiers: 0).problem == nil)  // F5
    }

    @Test func whatMacOSAnswersItselfIsRefused() {
        #expect(Shortcut(keyCode: 49, modifiers: Shortcut.command).problem == .system("Spotlight"))
    }

    @Test func theChoiceIsKeptAndNoneStaysNone() throws {
        // One fixed domain, emptied before and after: a new name each run left a preferences file per run, and macOS
        // writes the emptied domain back even after its file is deleted.
        let suite = "io.ballerine.pointe.tests.shortcut"
        let defaults = try #require(UserDefaults(suiteName: suite))
        defaults.removePersistentDomain(forName: suite)
        defer { defaults.removePersistentDomain(forName: suite) }
        #expect(Shortcut.stored(in: defaults) == .standard)
        let chosen = Shortcut(keyCode: 40, modifiers: Shortcut.control | Shortcut.shift)
        Shortcut.store(chosen, in: defaults)
        #expect(Shortcut.stored(in: defaults) == chosen && chosen.display == "⌃⇧K")
        Shortcut.store(nil, in: defaults)
        #expect(Shortcut.stored(in: defaults) == nil)
    }
}
@Suite struct ReleaseWatchTests {
    /// Feeds the samples in order and says after which one (from 1) the watch called the press released; nil: never.
    func released(after samples: [Bool]) -> Int? {
        var watch = ReleaseWatch()
        for (i, down) in samples.enumerated() where watch.sample(down: down) { return i + 1 }
        return nil
    }

    @Test func aKeySeenDownThenUpThreeTimesIsReleased() {
        #expect(released(after: [true, false, false, false]) == 4)
        #expect(released(after: [true, false, false]) == nil)
    }

    @Test func aBounceStartsTheCountAgain() {
        #expect(released(after: [true, false, false, true, false, false]) == nil)
        #expect(released(after: [true, false, false, true, false, false, false]) == 7)
    }

    @Test func aKeyNeverSeenDownNeverCutsAHold() {
        #expect(released(after: [Bool](repeating: false, count: 100)) == nil)
    }
}
#endif
