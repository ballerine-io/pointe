import Foundation

/// Which machine each session runs on, as the page shows it. With one machine every answer here is "as before". The
/// machine filter is a view only: it sends nothing and changes no mode. Pure, so it is unit tested.
public struct MachineView: Equatable, Sendable {
    public let here: String                // this Mac's name; empty from a Mac without machines
    public let names: [String]             // this Mac first, then the paired machines, then any a session names
    public let machines: [API.Machine]
    public let sessions: [API.Session]

    public init(_ status: API.Status?) {
        machines = status?.machines ?? []
        sessions = status?.sessions ?? []
        let here = machines.first(where: \.isHere)?.name ?? ""
        self.here = here
        var names: [String] = []
        for n in [here] + machines.filter({ !$0.isHere }).map(\.name) + sessions.map({ Self.of($0, here: here) })
        where !n.isEmpty && !names.contains(n) { names.append(n) }
        self.names = names
    }

    private static func of(_ s: API.Session, here: String) -> String { s.machine.flatMap { $0.isEmpty ? nil : $0 } ?? here }
    public func of(_ s: API.Session) -> String { Self.of(s, here: here) }
    public func info(_ name: String) -> API.Machine? { machines.first { $0.name == name } }
    public func isOffline(_ name: String) -> Bool { info(name)?.isOffline == true }

    /// Groups, chips and filter only once there is a second machine.
    public var multi: Bool { names.count > 1 }
    /// More than one machine has sessions: each session says where it runs.
    public var mixed: Bool { Set(sessions.map(of)).count > 1 }
    /// A filter on a machine that is gone (revoked) falls back to All.
    public func valid(_ filter: String?) -> String? { multi && filter.map(names.contains) == true ? filter : nil }
    public func shown(_ filter: String?) -> [API.Session] {
        guard let f = valid(filter) else { return sessions }
        return sessions.filter { of($0) == f }
    }
    public func onMachine(_ name: String) -> [API.Session] { sessions.filter { of($0) == name } }

    /// "shop · devbox" where the machine needs saying; a name suffixed with its machine ("shop devbox", the second shop
    /// to join) drops the suffix here.
    public func label(_ s: API.Session) -> String {
        let m = of(s), remote = m != here
        guard mixed || remote, !m.isEmpty else { return s.name }
        let base = remote && s.name.hasSuffix(" " + m) ? String(s.name.dropLast(m.count + 1)) : s.name
        return "\(base) · \(m)"
    }

    /// "devbox · Linux · 23 ms", "laptop · macOS · offline since 14:02", "studio · this Mac".
    public func header(_ name: String, now: Date = Date()) -> String {
        guard let m = info(name) else { return name }
        if m.isHere { return "\(name) · this Mac" }
        let state = m.isOffline ? "offline since \(MachineView.since(m.since, now: now))" : m.rtt_ms.map { "\($0) ms" } ?? "online"
        return [name, m.osName, state].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    /// "14:02" today, "Mon 14:02" before; "a while" when the daemon did not say.
    public static func since(_ t: Double?, now: Date = Date()) -> String {
        guard let t else { return "a while" }
        let d = Date(timeIntervalSince1970: t), f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = Calendar.current.isDate(d, inSameDayAs: now) ? "HH:mm" : "EEE HH:mm"
        return f.string(from: d)
    }
}
