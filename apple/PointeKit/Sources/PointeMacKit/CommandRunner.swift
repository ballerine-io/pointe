#if os(macOS)
import Foundation

public struct CommandResult: Sendable, Equatable {
    public let status: Int32
    public let output: String
    public let errors: String

    public init(status: Int32, output: String = "", errors: String = "") {
        self.status = status
        self.output = output
        self.errors = errors
    }
}

/// Runs a program and waits for it, off the main thread. Injected, so the locator is tested without one.
public protocol CommandRunning: Sendable {
    func run(_ executable: URL, _ arguments: [String], environment: [String: String]?, timeout: TimeInterval) async throws -> CommandResult
}

public struct ProcessRunner: CommandRunning {
    public init() {}

    public func run(_ executable: URL, _ arguments: [String], environment: [String: String]? = nil,
                    timeout: TimeInterval = 10) async throws -> CommandResult {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let process = Process()
                process.executableURL = executable
                process.arguments = arguments
                if let environment { process.environment = environment }
                let out = Pipe(), err = Pipe()
                process.standardOutput = out
                process.standardError = err
                process.standardInput = FileHandle.nullDevice
                do { try process.run() } catch { continuation.resume(throwing: error); return }
                let killer = DispatchWorkItem { if process.isRunning { process.terminate() } }
                DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: killer)
                // Read to the end before waiting: a full pipe would block the child. A detached grandchild (the daemon)
                // must not hold these pipes open: voice-daemon redirects its own output.
                let output = out.fileHandleForReading.readDataToEndOfFile()
                let errors = err.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                killer.cancel()
                continuation.resume(returning: CommandResult(status: process.terminationStatus,
                                                             output: String(decoding: output, as: UTF8.self),
                                                             errors: String(decoding: errors, as: UTF8.self)))
            }
        }
    }
}
#endif
