import Foundation

// A client that holds several machines (docs/design/multi-machine-clients.md): each pairing is a machine with its own
// voice, certificate, key and route, and a call goes to one of them, directly. Behind a flag until the iPhone UI
// tests prove the list, the switch and a machine that does not answer.

/// Settings → Labs → Several machines. Off: pairing replaces the machine, as before.
enum SeveralMachines {
    static let key = "pointe.labs.machines"

    static var on: Bool {
        #if DEBUG  // UI tests turn it on at launch
        if ProcessInfo.processInfo.environment["POINTE_MACHINES"] == "1" { return true }
        #endif
        return UserDefaults.standard.bool(forKey: key)
    }
}

/// One stored pairing and where it is kept.
struct VaultRow: Equatable, Sendable {
    let account: String
    let pairing: Pairing
    let ref: Data?
}

/// Where pairings are kept: the Keychain in the app (`KeychainVault`), memory in a test.
protocol PairingVault: Sendable {
    func rows() -> [VaultRow]
    /// True once written.
    func put(_ pairing: Pairing, account: String) -> Bool
    func delete(_ row: VaultRow)
}

/// Which machine a call goes to and the list's order: not secret, so not in the Keychain.
protocol MachineChoice: Sendable {
    var current: String? { get nonmutating set }
    var order: [String] { get nonmutating set }
}

struct DefaultsChoice: MachineChoice {
    nonisolated(unsafe) let defaults: UserDefaults
    init(_ defaults: UserDefaults = .standard) { self.defaults = defaults }
    var current: String? {
        get { defaults.string(forKey: "pointe.machines.current") }
        nonmutating set { defaults.set(newValue, forKey: "pointe.machines.current") }
    }
    var order: [String] {
        get { defaults.stringArray(forKey: "pointe.machines.order") ?? [] }
        nonmutating set { defaults.set(newValue, forKey: "pointe.machines.order") }
    }
}

/// The list of machines over a vault: one entry per machine, whatever was stored before.
struct PairedMachines {
    let vault: PairingVault
    let choice: MachineChoice

    /// One machine: the same id, or the same certificate (the same listener).
    static func same(_ a: Pairing, _ b: Pairing) -> Bool {
        (a.id != nil && a.id == b.id) || a.fingerprint == b.fingerprint
    }

    /// Each machine once, in the order the person set, then the rest as stored. An entry kept under its own key wins
    /// over an older copy of the same machine (the item saved before several machines).
    var ordered: [Pairing] {
        var seen: [Pairing] = []
        let rows = vault.rows().sorted { ($0.account == $0.pairing.storeKey ? 0 : 1, $0.account) < ($1.account == $1.pairing.storeKey ? 0 : 1, $1.account) }
        for row in rows where !seen.contains(where: { Self.same($0, row.pairing) }) { seen.append(row.pairing) }
        let order = choice.order
        return seen.sorted { (order.firstIndex(of: $0.storeKey) ?? Int.max) < (order.firstIndex(of: $1.storeKey) ?? Int.max) }
    }

    var current: Pairing? {
        let all = ordered
        return all.first { $0.storeKey == choice.current } ?? all.first
    }

    /// This machine in place of every other (one machine, as before several).
    func only(_ pairing: Pairing) {
        guard vault.put(pairing, account: pairing.storeKey) else { return }
        for row in vault.rows() where row.account != pairing.storeKey { vault.delete(row) }
        choice.order = [pairing.storeKey]
        choice.current = pairing.storeKey
    }

    /// Beside the others, and current. The same machine paired again (a new key, a new route) replaces its entry, and
    /// an older copy of it is deleted only once the new one is written.
    func add(_ pairing: Pairing, current makeCurrent: Bool = true) {
        let replaced = vault.rows().filter { Self.same($0.pairing, pairing) }
        let at = choice.order.firstIndex { key in replaced.contains { $0.pairing.storeKey == key } }
        guard vault.put(pairing, account: pairing.storeKey) else { return }
        for row in replaced where row.account != pairing.storeKey { vault.delete(row) }
        var order = choice.order.filter { key in !replaced.contains { $0.pairing.storeKey == key } && key != pairing.storeKey }
        order.insert(pairing.storeKey, at: min(at ?? order.count, order.count))
        choice.order = order
        if makeCurrent || replaced.contains(where: { $0.pairing.storeKey == choice.current }) { choice.current = pairing.storeKey }
    }

    func remove(_ pairing: Pairing) {
        for row in vault.rows() where Self.same(row.pairing, pairing) { vault.delete(row) }
        choice.order = choice.order.filter { $0 != pairing.storeKey }
        if choice.current == pairing.storeKey { choice.current = ordered.first?.storeKey }
    }

    func select(_ pairing: Pairing) {
        if ordered.contains(where: { $0.storeKey == pairing.storeKey }) { choice.current = pairing.storeKey }
    }

    func removeAll() {
        for row in vault.rows() { vault.delete(row) }
        choice.order = []
        choice.current = nil
    }
}

// MARK: - How each machine answers

/// What the list shows for a machine: answering, or why not and since when.
enum MachineReach: Equatable, Sendable {
    case unknown
    case answering(sessions: Int, need: Int)
    case down(ConnectionProblem, since: Date)

    var answers: Bool { if case .answering = self { true } else { false } }
}

enum MachineCopy {
    static let title = "Machines"
    static let footer = "Each machine runs its own Pointe, with its own keys. A call goes to the one you pick."
    static let add = "Add a machine"
    static let remove = "Remove"
    static let current = "Calls go here"
    static let checking = "Checking…"
    static let labs = "Several machines"
    static let labsHelp = "Keep more than one machine on this phone, and call any of them. Pairing a new one adds it."

    /// How this phone reaches it, as the person set it up.
    static func route(_ via: String?) -> String {
        switch via {
        case "tailscale": "Tailscale"
        case "wifi": "Wi-Fi"
        case "host": "Twingate or VPN"
        default: ""
        }
    }

    static func state(_ reach: MachineReach, now: Date = Date()) -> String {
        switch reach {
        case .unknown: return checking
        case .answering(let sessions, let need):
            let count = sessions == 1 ? "1 session" : "\(sessions) sessions"
            return need > 0 ? "\(count), \(need) need\(need == 1 ? "s" : "") you" : count
        case .down(let problem, let since):
            let f = DateFormatter()
            f.timeStyle = .short
            f.dateStyle = .none
            return "Not reachable since \(f.string(from: since)): \(problem.title)"
        }
    }

    /// "kite · Twingate or VPN · 3 sessions"
    static func line(_ p: Pairing, _ reach: MachineReach) -> String {
        [route(p.via), state(reach)].filter { !$0.isEmpty }.joined(separator: " · ")
    }
}

// MARK: - One alert per thing, across machines

/// The attention of every machine as one list (docs/design/multi-machine-clients.md, 1.6). A thing two machines list
/// (a session one machine runs and another links) is one alert; an action on it goes to the machine that runs it when
/// that machine is paired and answered, else to the machine that listed it.
enum AlertMerge {
    struct Source: Equatable {
        let key: String
        let name: String
        let machineId: String?
        let items: [API.Attention]
    }

    static func merge(_ sources: [Source]) -> [API.Attention] {
        guard sources.count > 1 else { return sources.first?.items ?? [] }  // one machine: its ids, as before
        var out: [API.Attention] = []
        var at: [String: Int] = [:]
        for source in sources {
            for item in source.items {
                var a = item
                let id = item.origin.map { "\(item.kind ?? "")|\($0)|\(item.request_id ?? "")" } ?? "\(source.key)|\(item.id)"
                a.id = id
                a.via = source.key
                if let title = a.title, !title.contains(source.name), !source.name.isEmpty { a.title = "\(title) · \(source.name)" }
                if let i = at[id] {
                    // The machine the session runs on answers for it.
                    let runsHere = source.machineId != nil && item.origin?.hasPrefix("\(source.machineId!)/") == true
                    if runsHere { out[i] = a }
                } else {
                    at[id] = out.count
                    out.append(a)
                }
            }
        }
        return out
    }
}
