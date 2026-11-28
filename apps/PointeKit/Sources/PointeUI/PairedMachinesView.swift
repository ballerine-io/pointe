#if os(iOS)
import SwiftUI

/// How each machine on this phone answers: checked every 15 seconds while the app is in front, each in parallel. A
/// machine's answer also names it (its id and name are kept) and brings its alerts in (AlertCenter).
@MainActor @Observable
final class MachinesWatch {
    static let every: Duration = .seconds(15)
    private(set) var reach: [String: MachineReach] = [:]
    private var downSince: [String: Date] = [:]

    func state(_ p: Pairing) -> MachineReach { reach[p.storeKey] ?? .unknown }

    /// The first other route that answers its status, pinned as always; none after a refusal (the caller checks).
    static func answering(_ p: Pairing) async -> Pairing.Route? {
        for route in RouteOrder.alternatives(p, ssh: false) {
            if (try? await API.standalone(DaemonLink(p.using(route))).status()) != nil { return route }
        }
        return nil
    }

    func run(_ flow: PairingFlow) async {
        while !Task.isCancelled {
            await check(flow)
            try? await Task.sleep(for: Self.every)
        }
    }

    func check(_ flow: PairingFlow) async {
        let current = flow.pairing?.storeKey
        await withTaskGroup(of: (Pairing, Result<API.Status, Error>).self) { group in
            for p in flow.pairings {
                group.addTask {
                    do { return (p, .success(try await API.standalone(DaemonLink(p)).status())) }
                    catch { return (p, .failure(error)) }
                }
            }
            for await (p, result) in group {
                switch result {
                case .success(let status):
                    downSince[p.storeKey] = nil
                    let here = status.machines?.first(where: \.isHere)
                    reach[p.storeKey] = .answering(sessions: status.sessions.count, need: here?.need ?? 0)
                    flow.learned(p, id: here?.machine_id, name: here?.name)
                    if let routes = status.routes, !routes.isEmpty { flow.learned(p, routes: routes) }
                    if p.storeKey != current {  // the current machine's alerts come from the call's own poll
                        await AlertCenter.shared.sync(status.attention, api: nil, machines: MachineView(status), from: p)
                    }
                case .failure(let error):
                    if case API.Failure.status = error {} else if let route = await Self.answering(p) {
                        flow.reroute(p, to: route)  // another of its routes answers: use it from now on
                        downSince[p.storeKey] = nil
                        reach[p.storeKey] = .unknown
                        continue
                    }
                    let link = DaemonLink(p)
                    let problem: ConnectionProblem? = if case API.Failure.status(let code, _) = error { link.problem(status: code) }
                        else { link.problem(error, pinRefused: false) }
                    let since = downSince[p.storeKey] ?? Date()
                    downSince[p.storeKey] = since
                    reach[p.storeKey] = .down(problem ?? ConnectionProblem(cause: .other("no answer"), host: p.host, port: p.port), since: since)
                }
            }
        }
    }
}

/// Over the call: the machine it goes to, and a tap opens the list.
struct MachineBar: View {
    let flow: PairingFlow
    let watch: MachinesWatch
    let open: () -> Void

    var body: some View {
        if let p = flow.pairing {
            Button(action: open) {
                HStack(spacing: 6) {
                    Circle().fill(watch.state(p).answers ? Brand.accent : Brand.muted).frame(width: 7, height: 7)
                    Text(p.label).font(.brand(.subheadline).weight(.semibold))
                    if flow.pairings.count > 1 { Text("· \(flow.pairings.count) machines").font(.brand(.footnote)).foregroundStyle(Brand.muted) }
                    Image(systemName: "chevron.down").font(.caption2)
                }
                .padding(.horizontal, 12).padding(.vertical, 6)
                .background(.thinMaterial, in: Capsule())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("machineBar")
            .accessibilityLabel("\(p.label), \(MachineCopy.state(watch.state(p))). Machines")
        }
    }
}

/// The machines on this phone: which way each is reached and whether it answers. A tap moves calls there (and the call
/// with it, when one is up); Remove takes one off this phone; Add a machine opens the scanner.
struct PairedMachinesSheet: View {
    let flow: PairingFlow
    let watch: MachinesWatch
    let switchTo: (Pairing) -> Void
    @State private var removing: Pairing?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(flow.pairings, id: \.storeKey) { p in
                        Button {
                            if p.storeKey != flow.pairing?.storeKey { switchTo(p) }
                            dismiss()
                        } label: {
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(p.label).font(.brand(.body).weight(.semibold))
                                    Text(MachineCopy.line(p, watch.state(p))).font(.brand(.footnote)).foregroundStyle(Brand.muted)
                                        .accessibilityIdentifier("machineState-\(p.label)")
                                }
                                Spacer()
                                if p.storeKey == flow.pairing?.storeKey {
                                    Image(systemName: "checkmark").foregroundStyle(Brand.accent).accessibilityLabel(MachineCopy.current)
                                }
                            }
                        }
                        .accessibilityIdentifier("machineRow-\(p.label)")
                        .swipeActions { Button(MachineCopy.remove, role: .destructive) { removing = p } }
                    }
                } footer: {
                    Text(MachineCopy.footer)
                }
                Section {
                    Button(MachineCopy.add, systemImage: "plus") { dismiss(); flow.pairAgain() }
                        .accessibilityIdentifier("addMachine")
                }
            }
            .navigationTitle(MachineCopy.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .task { await watch.check(flow) }
            .confirmationDialog("Remove \(removing?.label ?? "")?", isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }),
                                titleVisibility: .visible) {
                Button(MachineCopy.remove, role: .destructive) { if let removing { flow.remove(removing) }; removing = nil }
            } message: {
                Text("This phone stops talking to it until you scan its code again.")
            }
        }
    }
}
#endif
