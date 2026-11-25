import Foundation

/// Adding sessions the user already runs or ran lately (docs/design/attach-by-voice.md). The Mac lists them and holds
/// every rule; these carry its listing, the search over it, and the read-back that waits for a yes or a tap.
public enum AddSessions {
    /// One listed session (GET /voice/add-sessions). Its `key` goes back as it came: never a path.
    public struct Item: Decodable, Equatable, Identifiable, Sendable {
        public let key: String
        public let machine: String
        public let harness: String
        public let label: String
        public let name: String
        public let folder: String
        public let state: String       // "open" or "recent"
        public let ago: String?
        public let branch: String?
        public let first: String?
        public let approvals: Bool
        public let joinable: Bool
        public let why: String?
        public var id: String { key }

        public init(key: String, machine: String, harness: String, label: String, name: String, folder: String, state: String,
                    ago: String? = nil, branch: String? = nil, first: String? = nil, approvals: Bool = true, joinable: Bool = true,
                    why: String? = nil) {
            self.key = key
            self.machine = machine
            self.harness = harness
            self.label = label
            self.name = name
            self.folder = folder
            self.state = state
            self.ago = ago
            self.branch = branch
            self.first = first
            self.approvals = approvals
            self.joinable = joinable
            self.why = why
        }

        public var isOpen: Bool { state == "open" }
        /// Under the name: its folder, branch and how long ago.
        public var detail: String { [folder, branch ?? "", ago ?? ""].filter { !$0.isEmpty }.joined(separator: " · ") }

        /// Every word of the search is in its name, folder, branch, first request, machine or agent.
        public func matches(_ query: String) -> Bool {
            let words = query.lowercased().split(whereSeparator: \.isWhitespace)
            if words.isEmpty { return true }
            let hay = [name, folder, branch ?? "", first ?? "", machine, label].joined(separator: " ").lowercased()
            return words.allSatisfy { hay.contains($0) }
        }
    }

    public struct Listing: Decodable, Equatable, Sendable {
        public let open: [Item]
        public let recent: [Item]

        public init(open: [Item], recent: [Item]) {
            self.open = open
            self.recent = recent
        }

        /// A section per state (open first), and in it the machines in their order, each with its sessions by agent.
        public func sections(_ query: String) -> [(title: String, machines: [(name: String, items: [Item])])] {
            var out: [(title: String, machines: [(name: String, items: [Item])])] = []
            for (title, items) in [(AddSessionsCopy.open, open), (AddSessionsCopy.recent, recent)] {
                let shown = items.filter { $0.matches(query) }
                var order: [String] = []
                for item in shown where !order.contains(item.machine) { order.append(item.machine) }
                let machines = order.map { m in (name: m, items: shown.filter { $0.machine == m }.sorted { $0.label < $1.label }) }
                if !machines.isEmpty { out.append((title: title, machines: machines)) }
            }
            return out
        }
    }

    /// What the voice read back and waits on (`attach_pending` in /voice/status): `line` is its exact words. `choose`:
    /// it asked which one; a spoken pick or a tap on one of `choices` answers it.
    public struct Pending: Decodable, Equatable, Identifiable, Sendable {
        public struct Item: Decodable, Equatable, Sendable {
            public let key: String
            public let name: String
            public let state: String
        }

        /// A choice read back, as its button on the card: "Join billing", "Reopen docs".
        public struct Choice: Equatable, Sendable {
            public let key: String
            public let label: String
        }

        public let id: String
        public let line: String
        public let choose: Bool
        public let verb: String
        public let items: [Item]?

        public init(id: String, line: String, choose: Bool = false, verb: String = "join", items: [Item]? = nil) {
            self.id = id
            self.line = line
            self.choose = choose
            self.verb = verb
            self.items = items
        }

        public var button: String { verb == "reopen" ? AddSessionsCopy.reopen : AddSessionsCopy.join }

        /// The owner's live call: "which one?" showed only Cancel. Empty unless the voice asked which one.
        public var choices: [Choice] {
            guard choose else { return [] }
            return (items ?? []).map { Choice(key: $0.key, label: "\($0.state == "open" ? AddSessionsCopy.join : AddSessionsCopy.reopen) \($0.name)") }
        }
    }
}
