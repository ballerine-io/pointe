import Foundation

/// Starting a new session from Pointe (docs/design/new-session.md). The daemon holds every rule: which folders, which
/// agents, the name. These carry what it offers, what the sheet picked, and what it says is starting.
public enum NewSession {
    /// What the sheet offers (GET /voice/new-session). An item that is not available is shown, disabled, with its why.
    public struct Options: Decodable, Equatable, Sendable {
        public struct Agent: Decodable, Equatable, Identifiable, Sendable {
            public let name: String        // "claude-code", "opencode", "codex"
            public let title: String
            public let available: Bool
            public let why: String?
            public var id: String { name }

            public init(name: String, title: String, available: Bool = true, why: String? = nil) {
                self.name = name
                self.title = title
                self.available = available
                self.why = why
            }
        }

        public struct Machine: Decodable, Equatable, Identifiable, Sendable {
            public let name: String
            public let here: Bool?
            public let available: Bool
            public let why: String?
            public var id: String { name }

            public init(name: String, here: Bool? = nil, available: Bool = true, why: String? = nil) {
                self.name = name
                self.here = here
                self.available = available
                self.why = why
            }
        }

        /// A folder a session may start in. The path goes back to the daemon as it came: it is never typed.
        public struct Folder: Decodable, Equatable, Identifiable, Sendable {
            public let path: String
            public let name: String
            public var id: String { path }

            public init(path: String, name: String) {
                self.path = path
                self.name = name
            }
        }

        public let harnesses: [Agent]
        public let machines: [Machine]
        public let folders: [Folder]

        public init(harnesses: [Agent], machines: [Machine], folders: [Folder]) {
            self.harnesses = harnesses
            self.machines = machines
            self.folders = folders
        }

        /// The machine row shows only once there is a choice.
        public var showsMachines: Bool { machines.count > 1 }
    }

    /// What the sheet holds: an agent, a machine and a folder picked from the options, and the two optional fields.
    public struct Draft: Equatable, Sendable {
        public var harness: String?
        public var machine: String?
        public var folder: String?     // a path from the options
        public var name = ""
        public var prompt = ""

        public init() {}

        /// The first agent that can start, this Mac, and the first folder.
        public init(_ options: Options) {
            harness = options.harnesses.first(where: \.available)?.name
            machine = options.machines.first { $0.available && $0.here == true }?.name ?? options.machines.first(where: \.available)?.name
            folder = options.folders.first?.path
        }

        /// Start is offered only for an agent that can start, a machine that can take it, and a folder from the list.
        public func canStart(_ options: Options) -> Bool {
            options.harnesses.contains { $0.name == harness && $0.available }
                && options.folders.contains { $0.path == folder }
                && (machine == nil || options.machines.contains { $0.name == machine && $0.available })
        }

        /// The request's body. An empty name or prompt is left out: the daemon then names it after the folder.
        public var body: [String: String] {
            var body: [String: String] = [:]
            body["harness"] = harness
            body["folder"] = folder
            body["machine"] = machine
            let name = name.trimmingCharacters(in: .whitespacesAndNewlines), prompt = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
            if !name.isEmpty { body["name"] = name }
            if !prompt.isEmpty { body["prompt"] = prompt }
            return body
        }
    }

    /// A session between Start and its join, or one that did not start (`starting` in /voice/status).
    public struct Starting: Decodable, Equatable, Identifiable, Sendable {
        public let id: String
        public let name: String
        public let harness: String?
        public let label: String?      // the agent's name, as the daemon says it: "Claude Code"
        public let folder: String?
        public let state: String?      // starting, waiting, failed
        public let detail: String?     // why it failed

        public init(id: String, name: String, harness: String? = nil, label: String? = nil, folder: String? = nil, state: String? = nil, detail: String? = nil) {
            self.id = id
            self.name = name
            self.harness = harness
            self.label = label
            self.folder = folder
            self.state = state
            self.detail = detail
        }

        public var failed: Bool { state == "failed" }
        public var tag: String { failed ? NewSessionCopy.failed : NewSessionCopy.starting }
        /// The reason under a failed row; nothing under one that is still starting.
        public var why: String? { failed ? detail.flatMap { $0.isEmpty ? nil : $0 } : nil }
        public var agent: String { label.flatMap { $0.isEmpty ? nil : $0 } ?? Harness.name(harness) }
    }

    /// What the voice read back and waits to start (`start_pending` in /voice/status): `line` is its exact words.
    public struct Pending: Decodable, Equatable, Identifiable, Sendable {
        public let id: String
        public let line: String

        public init(id: String, line: String) {
            self.id = id
            self.line = line
        }
    }
}
