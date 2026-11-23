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

/// Starts each program disclaimed: macOS holds the program, not Pointe.app, responsible for it. The scripts it starts
/// sit in the plugin's folder, which any process of this user can edit, and a child the app is responsible for would
/// record under the app's microphone grant. The daemon needs none: call audio reaches it over the socket.
public struct ProcessRunner: CommandRunning {
    public init() {}

    private typealias Disclaim = @convention(c) (UnsafeMutablePointer<posix_spawnattr_t?>, Int32) -> Int32

    /// macOS's `responsibility_spawnattrs_setdisclaim`: in libSystem since macOS 10.14, not in its headers. The Mac app is
    /// built from source and not sold in the App Store; without the symbol the child is started as before.
    static var disclaim: (@convention(c) (UnsafeMutablePointer<posix_spawnattr_t?>, Int32) -> Int32)? {
        dlsym(UnsafeMutableRawPointer(bitPattern: -2), "responsibility_spawnattrs_setdisclaim").map { unsafeBitCast($0, to: Disclaim.self) }
    }

    public func run(_ executable: URL, _ arguments: [String], environment: [String: String]? = nil,
                    timeout: TimeInterval = 10) async throws -> CommandResult {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                do { continuation.resume(returning: try Self.spawn(executable, arguments, environment: environment, timeout: timeout)) }
                catch { continuation.resume(throwing: error) }
            }
        }
    }

    private static func spawn(_ executable: URL, _ arguments: [String], environment: [String: String]?,
                              timeout: TimeInterval) throws -> CommandResult {
        let out = Pipe(), err = Pipe()
        var actions: posix_spawn_file_actions_t?
        posix_spawn_file_actions_init(&actions)
        defer { posix_spawn_file_actions_destroy(&actions) }
        posix_spawn_file_actions_addopen(&actions, 0, "/dev/null", O_RDONLY, 0)
        posix_spawn_file_actions_adddup2(&actions, out.fileHandleForWriting.fileDescriptor, 1)
        posix_spawn_file_actions_adddup2(&actions, err.fileHandleForWriting.fileDescriptor, 2)
        var attrs: posix_spawnattr_t?
        posix_spawnattr_init(&attrs)
        defer { posix_spawnattr_destroy(&attrs) }
        // Only 0, 1 and 2 reach the child; signals as a fresh process has them.
        posix_spawnattr_setflags(&attrs, Int16(POSIX_SPAWN_CLOEXEC_DEFAULT | POSIX_SPAWN_SETSIGDEF | POSIX_SPAWN_SETSIGMASK))
        var none = sigset_t(), all = sigset_t()
        sigemptyset(&none)
        sigfillset(&all)
        posix_spawnattr_setsigmask(&attrs, &none)
        posix_spawnattr_setsigdefault(&attrs, &all)
        _ = disclaim?(&attrs, 1)

        let argv = [executable.path] + arguments
        let envp = (environment ?? ProcessInfo.processInfo.environment).map { "\($0.key)=\($0.value)" }
        var pid: pid_t = 0
        let started = withCStrings(argv) { argv in
            withCStrings(envp) { envp in posix_spawn(&pid, executable.path, &actions, &attrs, argv, envp) }
        }
        try? out.fileHandleForWriting.close()
        try? err.fileHandleForWriting.close()
        guard started == 0 else { throw POSIXError(POSIXErrorCode(rawValue: started) ?? .ENOENT) }

        let killer = DispatchWorkItem { kill(pid, SIGTERM) }
        DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: killer)
        // Both pipes are read to the end before waiting, side by side: a full pipe would block the child. A detached
        // grandchild (the daemon) must not hold them open: voice-daemon redirects its own output.
        final class Read: @unchecked Sendable { var data = Data() }  // written on one queue, read after the group waits
        let errors = Read(), reading = DispatchGroup()
        DispatchQueue.global().async(group: reading) { errors.data = err.fileHandleForReading.readDataToEndOfFile() }
        let output = out.fileHandleForReading.readDataToEndOfFile()
        reading.wait()
        var status: Int32 = 0
        while waitpid(pid, &status, 0) == -1 && errno == EINTR {}
        killer.cancel()
        let signal = status & 0x7f
        return CommandResult(status: signal == 0 ? (status >> 8) & 0xff : signal,
                             output: String(decoding: output, as: UTF8.self), errors: String(decoding: errors.data, as: UTF8.self))
    }

    /// A NULL-terminated array of C strings, alive for the call.
    private static func withCStrings<R>(_ strings: [String], _ body: ([UnsafeMutablePointer<CChar>?]) -> R) -> R {
        let pointers = strings.map { strdup($0) } + [nil]
        defer { pointers.forEach { free($0) } }
        return body(pointers)
    }
}
#endif
