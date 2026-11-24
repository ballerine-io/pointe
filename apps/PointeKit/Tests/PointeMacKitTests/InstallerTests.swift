#if os(macOS)
import CryptoKit
import Foundation
import Testing
@testable import PointeMacKit

/// The installer built into the Mac app: it runs install.sh only when the script is the one the app was built with and
/// installs the app's own version, and reads install.sh's own lines for its progress bar.
@Suite struct InstallerTests {
    static let repoScript = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        .appendingPathComponent("../../../../install.sh").standardized

    static func digest(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }

    func folder() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("pointe-installer-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    @Test func theAppCarriesTheHashOfTheRepositorysInstaller() throws {
        #expect(Self.digest(try Data(contentsOf: Self.repoScript)) == Installer.scriptSHA256,
                "install.sh changed: python3 tools/release_tarball.py app")
    }

    @Test func pinReadsTheTwoLinesReleaseTarballPinWrites() {
        let text = "#!/bin/bash\nPOINTE_VERSION=\"1.2.3\"  # a comment\nPOINTE_SHA256=\"\(String(repeating: "a", count: 64))\"  # x\n"
        #expect(Installer.pin(in: text).version == "1.2.3")
        #expect(Installer.pin(in: text).sha256.count == 64)
        #expect(Installer.pin(in: "POINTE_VERSION=\"1.2.3\"\nPOINTE_SHA256=\"\"\n").sha256 == "")
    }

    @Test func aScriptThatIsNotTheOneBuiltInIsNeverRun() async throws {
        let dir = try folder()
        defer { try? FileManager.default.removeItem(at: dir) }
        let script = dir.appendingPathComponent("install.sh")
        try "POINTE_VERSION=\"1.0.0\"\nPOINTE_SHA256=\"\(String(repeating: "b", count: 64))\"\necho changed\n".write(to: script, atomically: true, encoding: .utf8)
        let runner = FakeRunner()
        let installer = Installer(script: script, runner: runner)
        await #expect(throws: Installer.Problem.scriptChanged) {
            try await installer.install(appVersion: "1.0.0", environment: [:]) { _ in }
        }
        #expect(runner.ran.isEmpty)
        #expect(!installer.canInstall(appVersion: "1.0.0"))
    }

    @Test func noScriptIsSaidSo() {
        #expect(throws: Installer.Problem.noScript) { try Installer(script: nil, runner: FakeRunner()).checked(appVersion: "1.0.0") }
    }

    @Test func theRepositorysScriptInstallsOnlyTheVersionItPins() throws {
        let data = try Data(contentsOf: Self.repoScript)
        let pinned = Installer.pin(in: String(decoding: data, as: UTF8.self))
        let installer = Installer(script: Self.repoScript, runner: FakeRunner())
        #expect(throws: Installer.Problem.notPinned(script: pinned.version, app: "99.0.0")) { try installer.checked(appVersion: "99.0.0") }
        #expect(installer.canInstall(appVersion: pinned.version) == (pinned.sha256.count == 64))
    }

    @Test func progressFollowsInstallShsOwnLines() {
        let lines = [
            "Pointe 1.0.0, a conversational layer for your coding agents.", "Downloading Pointe 1.0.0...",
            "ok       SHA-256 matches (\(String(repeating: "c", count: 64)))", "ok       uv 0.12.21 installed in /Users/x/.local/bin",
            "Installing Pointe's Python packages (about 180 MB the first time)...", "ok       Pointe 1.0.0 is installed in ~/.pointe/1.0.0",
        ]
        let steps = lines.compactMap { Installer.progress(after: $0, version: "1.0.0") }
        #expect(steps.count == 4)
        #expect(steps.map(\.fraction) == steps.map(\.fraction).sorted())
        #expect(steps[1].line.contains("SHA-256 built into this app"))
        #expect(steps[2].slow)
        #expect(steps.last?.fraction ?? 0 > 0.9)
    }

    @Test func aFailureCarriesTheScriptsReasonWithoutItsName() async throws {
        let data = try Data(contentsOf: Self.repoScript)
        let pinned = Installer.pin(in: String(decoding: data, as: UTF8.self))
        guard pinned.sha256.count == 64 else { return }  // a build between releases installs nothing
        let runner = FakeRunner()
        runner.script = CommandResult(status: 1, errors: "install.sh: could not download https://example.invalid/x.tar.gz\n")
        await #expect(throws: Installer.Problem.failed("could not download https://example.invalid/x.tar.gz")) {
            try await Installer(script: Self.repoScript, runner: runner).install(appVersion: pinned.version, environment: [:]) { _ in }
        }
        let (bash, arguments, _) = try #require(runner.ran.first)
        #expect(bash.path == "/bin/bash")
        #expect(arguments.dropFirst() == ["--yes", "--version", pinned.version])
        #expect(!arguments[0].hasPrefix(Self.repoScript.deletingLastPathComponent().path), "it runs a private copy of what it checked")
    }
}

/// The real thing, opt-in (POINTE_LIVE_INSTALL=1 swift test --filter LiveInstall): the repository's install.sh, pinned to
/// a published release, run by the app's installer into a throwaway HOME, as on a Mac with nothing installed: uv,
/// Python and Pointe all downloaded and checked. It needs the network and about two minutes. No window, no Keychain.
@Suite struct LiveInstallTests {
    final class Steps: @unchecked Sendable {
        let lock = NSLock()
        var all: [Installer.Progress] = []
        func add(_ step: Installer.Progress) { lock.withLock { all.append(step) } }
    }

    @Test(.enabled(if: ProcessInfo.processInfo.environment["POINTE_LIVE_INSTALL"] != nil))
    func theAppsInstallerInstallsItsReleaseIntoAnEmptyHome() async throws {
        let script = InstallerTests.repoScript
        let pinned = Installer.pin(in: try String(contentsOf: script, encoding: .utf8))
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("pointe-live-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
        let env = ["HOME": home.path, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "TMPDIR": FileManager.default.temporaryDirectory.path,
                   "CLAUDE_VOICE_STATE": home.appendingPathComponent(".claude-voice").path, "LANG": "en_US.UTF-8"]
        let steps = Steps()
        let started = Date()
        try await Installer(script: script).install(appVersion: pinned.version, environment: env) { steps.add($0) }
        let root = home.appendingPathComponent(".pointe/\(pinned.version)")
        #expect(FileManager.default.fileExists(atPath: root.appendingPathComponent(".pointe-install").path))
        #expect(FileManager.default.isExecutableFile(atPath: root.appendingPathComponent(".venv/bin/python3").path))
        #expect(FileManager.default.isExecutableFile(atPath: home.appendingPathComponent(".local/bin/uv").path))
        #expect(FileManager.default.isExecutableFile(atPath: home.appendingPathComponent(".local/bin/pointe").path))
        #expect(PluginInstall(root: root)?.isStandalone == true)
        #expect(steps.all.contains { $0.line.contains("SHA-256 built into this app") })
        print("live install of \(pinned.version) into \(home.path): \(Int(Date().timeIntervalSince(started))) s; steps: "
              + steps.all.map { "\(Int($0.fraction * 100))% \($0.line)" }.joined(separator: " | "))
    }
}

@Suite struct StandaloneTests {
    @Test func onlyInstallShsFolderIsTheStandaloneInstall() throws {
        let box = try Sandbox()
        defer { box.remove() }
        let standalone = try box.plugin(".pointe/1.0.0", version: "1.0.0")
        try box.write("standalone 1.0.0 sha256 x\n", to: ".pointe/1.0.0/.pointe-install")
        let plugin = try box.plugin(".claude/plugins/cache/pointe/pointe/1.0.0", version: "1.0.0")
        #expect(PluginInstall(root: standalone)?.isStandalone == true)
        #expect(PluginInstall(root: plugin)?.isStandalone == false)
    }
}
#endif
