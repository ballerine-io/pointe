import SwiftUI
import UIKit

/// Settings → Machines (docs/multi-machine.md): the machines on this voice with their state and round trip, a one-time
/// code to pair another, and Revoke. Whoever holds a code can offer sessions to this voice, so the code shows only after
/// Face ID; Revoke asks first, then Face ID.
struct MachinesSheet: View {
    let status: API.Status?
    let pairing: Pairing
    let ownerCheck: (String) async -> Bool
    let invite: () async -> Result<API.Invite, MachinesFailure>
    let cancelInvite: () async -> MachinesFailure?
    let revoke: (String) async -> MachinesFailure?
    @State private var shown: API.Invite?       // the code, once Face ID passed here
    @State private var until: Date?
    @State private var unlocked = false
    @State private var problem: String?
    @State private var done: String?
    @State private var revoking: String?
    @State private var busy = false
    @Environment(\.dismiss) private var dismiss

    private var machines: [API.Machine] { (status?.machines ?? []).sorted { $0.isHere && !$1.isHere } }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    ForEach(machines) { m in row(m) }
                } footer: { Text(MachinesCopy.help) }
                Section { inviteSection }
                if let problem {
                    Text(problem).foregroundStyle(Brand.orange).accessibilityIdentifier("machinesProblem")
                }
                if let done {
                    Text(done).foregroundStyle(.secondary).accessibilityIdentifier("machinesDone")
                }
            }
            .scrollContentBackground(.hidden)
            .navigationTitle(MachinesCopy.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .confirmationDialog(revoking.map(MachinesCopy.revokeAsk) ?? "", isPresented: Binding(
                get: { revoking != nil }, set: { if !$0 { revoking = nil } }), titleVisibility: .visible, presenting: revoking) { name in
                Button("Revoke \(name)", role: .destructive) { Task { await revokeNow(name) } }
                    .accessibilityIdentifier("confirmRevoke")
                Button("Cancel", role: .cancel) {}
            }
            .onChange(of: status?.invite) { old, new in
                if let new, unlocked { shown = new; until = Date().addingTimeInterval(new.expires_in ?? 600) }
                else if new == nil, old != nil { shown = nil; until = nil }  // used, or cancelled on the Mac
            }
        }
    }

    private func row(_ m: API.Machine) -> some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(m.isHere ? "\(m.name) (this Mac)" : m.name).font(.body.weight(.semibold))
                Text(facts(m)).font(.caption).foregroundStyle(m.isOffline ? Brand.orange : .secondary)
            }
            Spacer()
            if !m.isHere {
                Button("Revoke", role: .destructive) { revoking = m.name }
                    .buttonStyle(.bordered).controlSize(.small)
                    .accessibilityIdentifier("revoke.\(m.name)")
                    .accessibilityLabel("Revoke \(m.name)")
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("machine.\(m.name)")
    }

    private func facts(_ m: API.Machine) -> String {
        let n = m.sessions ?? 0
        let state = m.isOffline ? "offline since \(MachinesCopy.since(m.since))" : m.isHere ? "online" : "online · \(m.rtt_ms.map { "\($0) ms" } ?? "…")"
        return [m.osName, state, "\(n) session\(n == 1 ? "" : "s")", m.key_fp.map { "key \($0)" } ?? ""]
            .filter { !$0.isEmpty }.joined(separator: " · ")
    }

    @ViewBuilder
    private var inviteSection: some View {
        if let shown, let until {
            TimelineView(.periodic(from: .now, by: 1)) { context in
                if let left = MachinesCopy.countdown(until.timeIntervalSince(context.date)) {
                    VStack(alignment: .leading, spacing: 10) {
                        Text(MachinesCopy.codeHelp).font(.footnote).foregroundStyle(.secondary)
                        Text(shown.code)
                            .font(.system(.largeTitle, design: .monospaced).weight(.bold)).kerning(3)
                            .textSelection(.enabled)
                            .accessibilityIdentifier("inviteCode")
                        Text(MachinesCopy.joinLine(shown, pairing: pairing))
                            .font(.system(.caption, design: .monospaced)).foregroundStyle(.secondary)
                            .textSelection(.enabled)
                            .accessibilityIdentifier("inviteLine")
                        Text("Expires in \(left)").font(.subheadline.monospacedDigit())
                            .accessibilityIdentifier("inviteCountdown")
                        HStack {
                            Button("Copy the line", systemImage: "doc.on.doc") {
                                UIPasteboard.general.string = MachinesCopy.joinLine(shown, pairing: pairing)
                            }
                            Spacer()
                            Button("Cancel the code", role: .destructive) { Task { await cancel() } }
                                .accessibilityIdentifier("cancelInvite")
                        }
                        .buttonStyle(.borderless)
                    }
                    .environment(\.layoutDirection, .leftToRight)  // a code and a command line read left to right
                } else {
                    Text("The code expired.").foregroundStyle(.secondary).accessibilityIdentifier("inviteExpired")
                }
            }
        } else {
            Button {
                Task { await makeInvite() }
            } label: {
                Label(status?.invite != nil ? "Show the code" : MachinesCopy.invite, systemImage: "faceid")
            }
            .disabled(busy)
            .accessibilityIdentifier("inviteMachine")
        }
    }

    private func makeInvite() async {
        busy = true; problem = nil; done = nil
        defer { busy = false }
        guard await ownerCheck(MachinesCopy.inviteReason) else { return }
        unlocked = true
        if let outstanding = status?.invite {  // made on the page: show it, do not make a second one
            shown = outstanding; until = Date().addingTimeInterval(outstanding.expires_in ?? 600)
            return
        }
        switch await invite() {
        case .success(let i): shown = i; until = Date().addingTimeInterval(i.expires_in ?? 600)
        case .failure(let f): problem = f.text
        }
    }

    private func cancel() async {
        if let f = await cancelInvite() { problem = f.text; return }
        shown = nil; until = nil
    }

    private func revokeNow(_ name: String) async {
        problem = nil; done = nil
        guard await ownerCheck("\(MachinesCopy.revokeReason): \(name)") else { return }
        if let f = await revoke(name) { problem = f.text } else { done = "\(name) is revoked." }
    }
}

/// The Mac's refusal, as a sentence: no pairing set up yet (pointe pair), the code gone, the machine unknown.
struct MachinesFailure: Error, Equatable {
    let text: String

    @MainActor static func from(_ error: Error) -> MachinesFailure {
        if case API.Failure.status(let code, let detail) = error {
            if code == 404 { return MachinesFailure(text: "This Mac's Pointe does not pair machines yet: update it.") }
            return MachinesFailure(text: CallView.sentence(detail))
        }
        return MachinesFailure(text: "The Mac did not answer.")
    }
}

// MARK: demo screens (Debug only): the machine fields as the design defines them. Every name is made up.

extension Demo {
    static func machinesJSON(_ screen: Screen, now: Double = Date().timeIntervalSince1970) -> String {
        let offline = screen == .machinesOffline
        let request = #"Bash: Run the tests\n{\"command\": \"uv run pytest -q\"}"#
        let caps = #"{"approvals": true, "side_questions": false}"#
        let one = screen == .machinesOne
        let sessions = one ? """
        [{"name": "billing/main", "working": true, "waiting": false, "needs": null, "machine": "", "online": true},
         {"name": "shop", "working": false, "waiting": false, "needs": null, "machine": "", "online": true}]
        """ : """
        [{"name": "billing/main", "working": true, "waiting": false, "needs": null, "machine": "", "online": true},
         {"name": "shop", "working": false, "waiting": false, "needs": null, "machine": "", "online": true},
         {"name": "shop devbox", "working": true, "waiting": \(!offline), "needs": null, "machine": "devbox", "online": true,
          "capabilities": \(caps), "request": \(offline ? "null" : "\"\(request)\""), "request_id": \(offline ? "null" : "\"r-dev-1\""), "voice_can_approve": true},
         {"name": "api", "working": false, "waiting": false, "needs": "which retry budget to use", "machine": "devbox", "online": true, "capabilities": \(caps)},
         {"name": "חנות", "working": false, "waiting": false, "needs": null, "machine": "devbox", "online": true, "capabilities": \(caps)},
         {"name": "notes", "working": false, "waiting": \(offline), "needs": null, "machine": "laptop", "online": false,
          "capabilities": \(caps), "request": \(offline ? "\"\(request)\"" : "null"), "request_id": \(offline ? "\"r-lap-1\"" : "null"), "voice_can_approve": true}]
        """
        let machines = one ? """
        [{"id": "hub", "name": "studio", "here": true, "os": "macos", "online": true, "sessions": 2, "need": 0}]
        """ : """
        [{"id": "hub", "name": "studio", "here": true, "os": "macos", "online": true, "sessions": 2, "need": 0},
         {"id": "n3f2a1", "name": "devbox", "here": false, "os": "linux", "online": true, "sessions": 3, "need": 2, "rtt_ms": 23, "key_fp": "3f2a9c41d07be215"},
         {"id": "n91c0de", "name": "laptop", "here": false, "os": "macos", "online": false, "since": \(now - 1800), "sessions": 1, "need": 0, "key_fp": "91c0de77aa013b42"}]
        """
        return """
        {"active": "billing/main", "connected": true, "mode": "orchestrator", "polish": false, "hearing": "",
         "sessions": \(sessions), "machines": \(machines), "invite": null,
         "talk": [{"id": 1, "who": "user", "text": "what's going on everywhere", "typed": false, "corrected": false},
                  {"id": 2, "who": "assistant", "text": "On studio, billing is running its tests. On devbox, shop wants to run the tests and api needs a retry budget. The laptop is offline."}]}
        """
    }

    static let demoInvite = API.Invite(code: "K7PQ-2MXD", expires_in: 600, link: nil)
}
