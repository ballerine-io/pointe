#if os(macOS)
import Darwin
import Foundation
import LocalAuthentication
import SwiftUI

/// The Mac app's own SSH tunnel to a machine (SSHRoute): /usr/bin/ssh with the user's configuration and agent, a free
/// local port forwarded to the machine's 127.0.0.1:7443. Open once the forward accepts a connection; closed with the
/// call's machine.
final class SSHTunnel: @unchecked Sendable {
    let port: Int
    private let process: Process

    private init(port: Int, process: Process) { self.port = port; self.process = process }

    struct Failed: Error, CustomStringConvertible { let description: String }

    static func open(target: String, remote: Int, wait: Duration = .seconds(15)) async throws -> SSHTunnel {
        guard SSHRoute.valid(target) else { throw Failed(description: "Not an SSH target: \(target)") }
        let port = freePort()
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/ssh")
        process.arguments = SSHRoute.arguments(target: target, local: port, remote: remote)
        let errors = Pipe()
        process.standardError = errors
        process.standardOutput = FileHandle.nullDevice
        process.standardInput = FileHandle.nullDevice
        try process.run()
        let deadline = ContinuousClock.now + wait
        while ContinuousClock.now < deadline {
            if !process.isRunning {
                let said = String(data: errors.fileHandleForReading.availableData, encoding: .utf8)?
                    .split(separator: "\n").first.map(String.init) ?? "ssh ended"
                throw Failed(description: "ssh to \(target) failed: \(said)")
            }
            if accepts(port) { return SSHTunnel(port: port, process: process) }
            try? await Task.sleep(for: .milliseconds(200))
        }
        process.terminate()
        throw Failed(description: "ssh to \(target) did not open its forward in time")
    }

    func close() { if process.isRunning { process.terminate() } }

    private static func freePort() -> Int {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        defer { Darwin.close(fd) }
        var address = sockaddr_in(sin_len: UInt8(MemoryLayout<sockaddr_in>.size), sin_family: sa_family_t(AF_INET), sin_port: 0,
                                  sin_addr: in_addr(s_addr: inet_addr("127.0.0.1")), sin_zero: (0, 0, 0, 0, 0, 0, 0, 0))
        var length = socklen_t(MemoryLayout<sockaddr_in>.size)
        _ = withUnsafeMutablePointer(to: &address) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(fd, $0, length) } }
        _ = withUnsafeMutablePointer(to: &address) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(fd, $0, &length) } }
        return Int(UInt16(bigEndian: address.sin_port))
    }

    private static func accepts(_ port: Int) -> Bool {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        defer { Darwin.close(fd) }
        var address = sockaddr_in(sin_len: UInt8(MemoryLayout<sockaddr_in>.size), sin_family: sa_family_t(AF_INET),
                                  sin_port: in_port_t(UInt16(port).bigEndian), sin_addr: in_addr(s_addr: inet_addr("127.0.0.1")),
                                  sin_zero: (0, 0, 0, 0, 0, 0, 0, 0))
        return withUnsafeMutablePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { connect(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) == 0 }
        }
    }
}

/// Over the Mac app's call screen, with several machines on: the machine the call goes to, this Mac first, and Add.
struct MacMachineMenu: View {
    let session: MacSession
    @State private var adding = false

    var body: some View {
        Menu {
            Button("This Mac") { Task { await session.use(nil) } }.accessibilityIdentifier("machineThisMac")
            ForEach(session.machines, id: \.storeKey) { p in
                Button("\(p.label) · \(MachineCopy.route(p.via))") { Task { await session.use(p) } }
                    .accessibilityIdentifier("machineItem-\(p.label)")
            }
            Divider()
            Button(MachineCopy.add + "…") { adding = true }.accessibilityIdentifier("addMachine")
        } label: {
            Text(session.remote?.label ?? "This Mac").font(.brand(.subheadline).weight(.semibold))
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .accessibilityIdentifier("machineMenu")
        .sheet(isPresented: $adding) { MacAddMachineSheet(session: session) }
    }
}

/// Add a machine to this Mac app: the line `pointe pair <method>` printed on it, or its page's code. Touch ID or the
/// password first, as on the iPhone: it opens a microphone into more sessions.
struct MacAddMachineSheet: View {
    let session: MacSession
    @State private var line = ""
    @State private var problem: String?
    @State private var working = false
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(MachineCopy.add).font(.brand(.headline))
            Text("Paste the pointe://pair line from the machine: pointe pair tailscale, wifi, host or ssh there, or its page's Settings, Phone.")
                .font(.brand(.footnote)).foregroundStyle(Brand.muted)
            TextField("pointe://pair?…", text: $line).textFieldStyle(.roundedBorder).accessibilityIdentifier("addMachineLine")
            if let problem { Text(problem).foregroundStyle(Brand.accent).accessibilityIdentifier("addMachineProblem") }
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }
                Button("Add") {
                    working = true
                    Task {
                        problem = await session.add(line)
                        working = false
                        if problem == nil { dismiss() }
                    }
                }
                .keyboardShortcut(.defaultAction).disabled(working || line.isEmpty).accessibilityIdentifier("addMachineConfirm")
            }
        }
        .padding(20).frame(width: 440)
    }
}
#endif
