#if os(macOS)
import Darwin
import Foundation
import Testing
@testable import PointeMacKit

/// The plugin's scripts run as the app's children (SECURITY.md, "The Mac app"). macOS would hold Pointe.app responsible
/// for them, so a script someone edited would record under the app's microphone grant: they are started disclaimed.
@Suite(.serialized) struct CommandRunnerTests {
    let runner = ProcessRunner()

    @Test func itRunsAProgramAndReturnsItsStatusAndBothOutputs() async throws {
        let result = try await runner.run(URL(fileURLWithPath: "/bin/sh"), ["-c", "echo out; echo err >&2; exit 3"], environment: nil, timeout: 10)
        #expect(result == CommandResult(status: 3, output: "out\n", errors: "err\n"))
    }

    @Test func itPassesOnlyTheEnvironmentItIsGivenAndNoInput() async throws {
        let env = try await runner.run(URL(fileURLWithPath: "/usr/bin/env"), [], environment: ["POINTE_ONLY": "this"], timeout: 10)
        #expect(env.output == "POINTE_ONLY=this\n")
        let cat = try await runner.run(URL(fileURLWithPath: "/bin/cat"), [], environment: [:], timeout: 10)
        #expect(cat.status == 0 && cat.output.isEmpty, "stdin is /dev/null: nothing waits on it")
    }

    @Test func aProgramThatRunsTooLongIsStopped() async throws {
        let start = Date()
        let result = try await runner.run(URL(fileURLWithPath: "/bin/sleep"), ["30"], environment: [:], timeout: 0.5)
        #expect(Date().timeIntervalSince(start) < 10 && result.status != 0)
    }

    @Test func aMissingProgramThrows() async {
        await #expect(throws: (any Error).self) {
            try await runner.run(URL(fileURLWithPath: "/nonexistent/voice-daemon"), [], environment: [:], timeout: 5)
        }
    }

    /// A macOS without the call, or one that refuses it, must not start the script as the app's child anyway: it would
    /// record under the app's microphone grant. Nothing runs, and the error says why.
    @Test func withoutTheDisclaimNothingStarts() async throws {
        let ran = FileManager.default.temporaryDirectory.appendingPathComponent("pointe-disclaim-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: ran) }
        for broken in [ProcessRunner(disclaim: nil), ProcessRunner(disclaim: { _, _ in 22 })] {
            await #expect(throws: ProcessRunner.NotDisclaimed.self) {
                try await broken.run(URL(fileURLWithPath: "/usr/bin/touch"), [ran.path], environment: [:], timeout: 5)
            }
            #expect(!FileManager.default.fileExists(atPath: ran.path), "the program never ran")
        }
        #expect(ProcessRunner.NotDisclaimed().localizedDescription.contains("can't start"))
    }

    @Test func theChildIsResponsibleForItselfNotThisApp() async throws {
        typealias Responsible = @convention(c) (pid_t) -> pid_t
        let symbol = try #require(dlsym(UnsafeMutableRawPointer(bitPattern: -2), "responsibility_get_pid_responsible_for_pid"))
        let responsible = unsafeBitCast(symbol, to: Responsible.self)
        let child = Task { try await runner.run(URL(fileURLWithPath: "/bin/sleep"), ["2"], environment: [:], timeout: 10) }
        var pid: pid_t = 0
        for _ in 0..<40 where pid == 0 {
            try await Task.sleep(for: .milliseconds(50))
            let found = Process()
            found.executableURL = URL(fileURLWithPath: "/usr/bin/pgrep")
            found.arguments = ["-P", String(getpid()), "-x", "sleep"]
            let out = Pipe()
            found.standardOutput = out
            try found.run()
            found.waitUntilExit()
            pid = pid_t(String(decoding: out.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
                .split(whereSeparator: \.isNewline).first.map(String.init) ?? "") ?? 0
        }
        #expect(pid > 0, "the child was found")
        #expect(responsible(pid) == pid, "disclaimed: macOS holds the script itself responsible, not this process")
        #expect(responsible(getpid()) != pid)
        _ = try await child.value
    }
}
#endif
