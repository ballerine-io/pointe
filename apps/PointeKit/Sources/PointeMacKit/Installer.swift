#if os(macOS)
import CryptoKit
import Foundation

/// Installs Pointe on a Mac that has none, or updates the standalone install to this app's version, by running
/// install.sh itself: the copy built into the app, which must be the repository's byte for byte and pinned to the app's
/// own version. The script does the rest as it does in a terminal: the release tarball checked against the SHA-256
/// pinned in it, uv installed the checked way, `~/.local/bin/pointe` linked. No Terminal, no sudo.
public struct Installer: Sendable {
    /// install.sh's SHA-256. `tools/release_tarball.py pin` and `app` write it; tests/test_install.py holds it to the file.
    public static let scriptSHA256 = "9b64170601576912b84757424c22d3e8b300eed5fb8feb1001275e838b2c0df1"

    public enum Problem: Error, Equatable, Sendable {
        /// The app was built without install.sh.
        case noScript
        /// The script in the app is not the one this app was built to run.
        case scriptChanged
        /// The script installs another version than the app's, or carries no SHA-256 for it: a build between releases.
        case notPinned(script: String, app: String)
        /// install.sh stopped: its last lines, which name the reason.
        case failed(String)

        public var line: String {
            switch self {
            case .noScript: "This copy of the app has no installer in it. Download Pointe again from its release page."
            case .scriptChanged: "The installer inside this app is not the one it was built with, so it was not run. Download Pointe again from its release page."
            case .notPinned(let script, let app): "This build of the app (\(app)) has no checked release to install (its installer names \(script.isEmpty ? "none" : script)). Install Pointe with install.sh, or use a released app."
            case .failed(let why): why.isEmpty ? "The install stopped. Try again." : why
            }
        }
    }

    public struct Progress: Equatable, Sendable {
        public let fraction: Double
        public let line: String
        /// The long step: the Python packages, about 180 MB. A progress bar may creep while it runs.
        public let slow: Bool

        public init(_ fraction: Double, _ line: String, slow: Bool = false) {
            self.fraction = fraction
            self.line = line
            self.slow = slow
        }
    }

    public let script: URL?
    private let runner: any CommandRunning

    public init(script: URL? = Bundle.main.url(forResource: "install", withExtension: "sh"), runner: any CommandRunning = ProcessRunner()) {
        self.script = script
        self.runner = runner
    }

    /// The release install.sh installs: `POINTE_VERSION` and `POINTE_SHA256`, the two lines `release_tarball.py pin` writes.
    public static func pin(in text: String) -> (version: String, sha256: String) {
        func value(_ name: String) -> String {
            guard let line = text.split(separator: "\n").first(where: { $0.hasPrefix("\(name)=\"") }) else { return "" }
            return line.dropFirst(name.count + 2).prefix { $0 != "\"" }.description
        }
        return (value("POINTE_VERSION"), value("POINTE_SHA256"))
    }

    /// The script's bytes, once they are the ones this app was built with and they install `appVersion`, checked.
    public func checked(appVersion: String) throws -> Data {
        guard let script, let data = try? Data(contentsOf: script) else { throw Problem.noScript }
        let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        guard digest == Self.scriptSHA256 else { throw Problem.scriptChanged }
        let pin = Self.pin(in: String(decoding: data, as: UTF8.self))
        guard pin.version == appVersion, pin.sha256.count == 64 else { throw Problem.notPinned(script: pin.version, app: appVersion) }
        return data
    }

    /// Whether this app can install its own version at all (a released build), without running anything.
    public func canInstall(appVersion: String) -> Bool { (try? checked(appVersion: appVersion)) != nil }

    /// Runs the checked script from a private copy (what was checked is what runs): `install.sh --yes --version <app>`.
    /// It installs the app's version, or changes nothing when a newer standalone install is there already.
    public func install(appVersion: String, environment: [String: String],
                        progress: @escaping @Sendable (Progress) -> Void) async throws {
        let data = try checked(appVersion: appVersion)
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("pointe-install-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: folder) }
        let copy = folder.appendingPathComponent("install.sh")
        try data.write(to: copy)
        progress(Progress(0.02, "Starting…"))
        let result = try await runner.run(URL(fileURLWithPath: "/bin/bash"), [copy.path, "--yes", "--version", appVersion],
                                          environment: environment, timeout: 1800) { line in
            if let step = Self.progress(after: line, version: appVersion) { progress(step) }
        }
        guard result.status == 0 else {
            throw Problem.failed(DaemonLocator.lastLines(result.errors.isEmpty ? result.output : result.errors, 2)
                .replacingOccurrences(of: "install.sh: ", with: ""))
        }
        progress(Progress(1, "Pointe \(appVersion) is installed."))
    }

    /// What a line install.sh printed means for the progress bar; nil for a line that moves nothing.
    static func progress(after line: String, version: String) -> Progress? {
        let text = line.trimmingCharacters(in: .whitespaces)
        if text.hasPrefix("Downloading Pointe") { return Progress(0.08, "Downloading Pointe \(version) from GitHub…") }
        if text.hasPrefix("ok") && text.contains("SHA-256 matches") {
            return Progress(0.25, "Checked: the download matches the SHA-256 built into this app. Installing uv…")
        }
        if text.hasPrefix("Installing Pointe's Python packages") {
            return Progress(0.35, "Installing Pointe's Python: about 180 MB the first time, under a minute on a fast connection…", slow: true)
        }
        if text.hasPrefix("ok") && text.contains("is installed in") { return Progress(0.97, "Pointe \(version) is installed.") }
        if text.contains("is installed already, newer than") { return Progress(0.97, "A newer Pointe is installed already.") }
        return nil
    }
}
#endif
