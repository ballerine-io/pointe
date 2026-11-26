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
            /// Whose machine it is, on one somebody invited this voice to; nil on your own.
            public var owner: String? = nil
            public var id: String { name }

            public init(name: String, here: Bool? = nil, available: Bool = true, why: String? = nil, owner: String? = nil) {
                self.name = name
                self.here = here
                self.available = available
                self.why = why
                self.owner = owner
            }
        }

        /// With `?machine=avi-box`: the machine the folders and agents are of, how its new sessions start (its owner's
        /// setting, "skip" or "ask"), and the account they run as.
        public struct Target: Decodable, Equatable, Sendable {
            public let name: String
            public var owner: String? = nil
            public var permissions: String? = nil
            public var account: String? = nil

            public init(name: String, owner: String? = nil, permissions: String? = nil, account: String? = nil) {
                self.name = name
                self.owner = owner
                self.permissions = permissions
                self.account = account
            }

            /// How that machine starts the sessions people ask it for, as the voice says it (machines.start_default_line).
            public var startsLine: String {
                guard permissions == "skip" else { return "\(name) starts sessions that ask before actions." }
                let account = (account ?? "").isEmpty ? "" : " as \(account ?? "")"
                return "\(name) starts sessions that skip permission prompts: it can edit files and run commands\(account) without asking."
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
        /// Set when these are another machine's folders and agents; nil for this Mac's own.
        public var machine: Target? = nil

        public init(harnesses: [Agent], machines: [Machine], folders: [Folder], machine: Target? = nil) {
            self.harnesses = harnesses
            self.machines = machines
            self.folders = folders
            self.machine = machine
        }

        /// The machine these options are of: the one asked for, else this Mac.
        public var of: String? { machine?.name ?? machines.first { $0.here == true }?.name }

        /// Picking this machine needs its own folders and agents: they are not the ones shown now.
        public func needsLoad(for name: String?) -> Bool { name != nil && name != of }

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

        /// Another machine's options arrived: the machine stays, the name and the prompt stay, and the agent and the
        /// folder are kept only when that machine has them too.
        public mutating func adopt(_ options: Options, machine: String?) {
            self.machine = machine
            if !options.harnesses.contains(where: { $0.name == harness && $0.available }) { harness = options.harnesses.first(where: \.available)?.name }
            if !options.folders.contains(where: { $0.path == folder }) { folder = options.folders.first?.path }
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
        public let notice: String?     // the risk line, the first time a start skips permission prompts (SKIP_NOTICE)
        public var machine: String? = nil  // the machine it starts on, when that is not this Mac
        public var by: String? = nil       // on the machine: the person who asked for it

        public init(id: String, name: String, harness: String? = nil, label: String? = nil, folder: String? = nil, state: String? = nil, detail: String? = nil, notice: String? = nil,
                    machine: String? = nil, by: String? = nil) {
            self.machine = machine
            self.by = by
            self.id = id
            self.name = name
            self.harness = harness
            self.label = label
            self.folder = folder
            self.state = state
            self.detail = detail
            self.notice = notice
        }

        public var failed: Bool { state == "failed" }
        public var tag: String { failed ? NewSessionCopy.failed : NewSessionCopy.starting }
        /// The reason under a failed row; under one still starting, the risk line its start carries, if any.
        public var why: String? { (failed ? detail : notice).flatMap { $0.isEmpty ? nil : $0 } }
        public var agent: String { label.flatMap { $0.isEmpty ? nil : $0 } ?? Harness.name(harness) }
    }

    /// What the voice read back and waits to start (`start_pending` in /voice/status): `line` is its exact words.
    public struct Pending: Decodable, Equatable, Identifiable, Sendable {
        public let id: String
        public let line: String
        public var machine: String? = nil  // the machine a yes would start it on, when that is not this Mac

        public init(id: String, line: String, machine: String? = nil) {
            self.id = id
            self.line = line
            self.machine = machine
        }
    }
}
