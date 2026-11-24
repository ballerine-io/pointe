import Foundation

/// The night shift (docs/design/night-shift.md): tasks for the sessions while the person is away. The daemon holds every
/// rule: what a shift may send, that it approves nothing, the caps. These carry what it offers, what the sheet picked,
/// how a shift stands and what its ledger says.
public enum NightShift {
    /// One session on a shift, with the task it is on.
    public struct Front: Decodable, Equatable, Sendable {
        public let session: String
        public let harness: String
        public let state: String       // starting, working, waiting, parked, finished
        public let task: String
        public let done: Int
        public let total: Int

        public init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            session = c.take(.session, or: "")
            harness = c.take(.harness, or: "")
            state = c.take(.state, or: "")
            task = c.take(.task, or: "")
            done = c.take(.done, or: 0)
            total = c.take(.total, or: 0)
        }

        enum CodingKeys: String, CodingKey { case session, harness, state, task, done, total }
    }

    /// How a shift stands (`night_shift` in /voice/status, and each of the last seven). Only `id` must be there: a count
    /// the Mac did not send is zero.
    public struct Summary: Decodable, Equatable, Identifiable, Sendable {
        public var on: Bool
        public let id: String
        public let at: Double
        public let ends_at: Double
        public let ended: Double?
        public let why: String         // "", complete, hours, messages, stopped
        public let sent: Int
        public let budget: Int
        public let hours: Double
        public let notify: Bool
        public let tasks: Int
        public let done: Int
        public let in_flight: Int
        public let blocked: Int
        public let decided: Int
        public let asked: Int
        public let fronts: [Front]

        public init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            id = try c.decode(String.self, forKey: .id)
            on = c.take(.on, or: false)
            at = c.take(.at, or: 0)
            ends_at = c.take(.ends_at, or: 0)
            ended = try? c.decodeIfPresent(Double.self, forKey: .ended)
            why = c.take(.why, or: "")
            sent = c.take(.sent, or: 0)
            budget = c.take(.budget, or: 0)
            hours = c.take(.hours, or: 0)
            notify = c.take(.notify, or: false)
            tasks = c.take(.tasks, or: 0)
            done = c.take(.done, or: 0)
            in_flight = c.take(.in_flight, or: 0)
            blocked = c.take(.blocked, or: 0)
            decided = c.take(.decided, or: 0)
            asked = c.take(.asked, or: 0)
            fronts = c.take(.fronts, or: [])
        }

        enum CodingKeys: String, CodingKey {
            case on, id, at, ends_at, ended, why, sent, budget, hours, notify, tasks, done, in_flight, blocked, decided, asked, fronts
        }

        /// The strip's line, as the page says it (`nightLine` in ui.html): "1 of 3 done · 1 blocked".
        public var statusLine: String { "\(done) of \(tasks) done · \(blocked) blocked" }
    }

    /// One line of the ledger. A field that does not apply to its kind is empty.
    public struct Entry: Decodable, Equatable, Identifiable, Sendable {
        public let id: String
        public let kind: String        // done, blocked, decided, asked
        public let session: String
        public let task: String
        public let at: Double
        public let text: String
        public let proof: String
        public let commit: String
        public let pr: String
        public let waits_on: String
        public let request: String     // an approval request, word for word
        public let request_id: String
        public let question: String
        public let choice: String
        public let otherwise: String
        public let resolved: String    // "approved by you", "denied by you", "answered by you: …"
        public let resolved_at: Double

        public init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            id = c.take(.id, or: "")
            kind = c.take(.kind, or: "")
            session = c.take(.session, or: "")
            task = c.take(.task, or: "")
            at = c.take(.at, or: 0)
            text = c.take(.text, or: "")
            proof = c.take(.proof, or: "")
            commit = c.take(.commit, or: "")
            pr = c.take(.pr, or: "")
            waits_on = c.take(.waits_on, or: "")
            request = c.take(.request, or: "")
            request_id = c.take(.request_id, or: "")
            question = c.take(.question, or: "")
            choice = c.take(.choice, or: "")
            otherwise = c.take(.otherwise, or: "")
            resolved = c.take(.resolved, or: "")
            resolved_at = c.take(.resolved_at, or: 0)
        }

        enum CodingKeys: String, CodingKey {
            case id, kind, session, task, at, text, proof, commit, pr, waits_on, request, request_id, question, choice, otherwise, resolved, resolved_at
        }
    }

    /// A task a session is on now, or one it has not reached.
    public struct Queued: Decodable, Equatable, Sendable {
        public let session: String
        public let task: String

        public init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            session = c.take(.session, or: "")
            task = c.take(.task, or: "")
        }

        enum CodingKeys: String, CodingKey { case session, task }
    }

    /// The ledger's parts, in the order every screen shows them. The order is a product rule: what was decided without
    /// the person and what waits on them come before what was done.
    public enum Section: String, CaseIterable, Sendable {
        case decided, asked, done, blocked, inFlight, notStarted

        public var title: String {
            switch self {
            case .decided: NightShiftCopy.decided
            case .asked: NightShiftCopy.asked
            case .done: NightShiftCopy.done
            case .blocked: NightShiftCopy.blocked
            case .inFlight: NightShiftCopy.inFlight
            case .notStarted: NightShiftCopy.notStarted
            }
        }
    }

    public struct Ledger: Decodable, Equatable, Sendable {
        public let done: [Entry]
        public let in_flight: [Queued]
        public let blocked: [Entry]
        public let decided: [Entry]
        public let asked: [Entry]
        public let not_started: [Queued]

        public init() { (done, in_flight, blocked, decided, asked, not_started) = ([], [], [], [], [], []) }

        public init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            done = c.take(.done, or: [])
            in_flight = c.take(.in_flight, or: [])
            blocked = c.take(.blocked, or: [])
            decided = c.take(.decided, or: [])
            asked = c.take(.asked, or: [])
            not_started = c.take(.not_started, or: [])
        }

        enum CodingKeys: String, CodingKey { case done, in_flight, blocked, decided, asked, not_started }

        public func count(_ section: Section) -> Int {
            switch section {
            case .decided: decided.count
            case .asked: asked.count
            case .done: done.count
            case .blocked: blocked.count
            case .inFlight: in_flight.count
            case .notStarted: not_started.count
            }
        }

        /// The parts that have something in them, in the product's order.
        public var sections: [Section] { Section.allCases.filter { count($0) > 0 } }
    }

    /// One part of the morning report, as the briefing says it.
    public struct Morning: Decodable, Equatable, Sendable {
        public let kind: String        // headline, decided, asked, done, blocked, in_flight
        public let title: String?
        public let text: String
    }

    /// A shift with its ledger: the running one, the last one, or one picked from the history.
    public struct Shift: Decodable, Equatable, Identifiable, Sendable {
        public let summary: Summary
        public let how: String
        public let ledger: Ledger
        public let morning: [Morning]

        public init(from decoder: Decoder) throws {
            summary = try Summary(from: decoder)
            let c = try decoder.container(keyedBy: CodingKeys.self)
            how = c.take(.how, or: "")
            ledger = c.take(.ledger, or: Ledger())
            morning = c.take(.morning, or: [])
        }

        enum CodingKeys: String, CodingKey { case how, ledger, morning }

        public var id: String { summary.id }
        public var on: Bool { summary.on }
        /// The report's first line: when it ran, how much got done, how it ended.
        public var headline: String? { morning.first.map(\.text).flatMap { $0.isEmpty ? nil : $0 } }
    }

    /// What the voice read back and waits to start (`shift_pending` in /voice/status): `line` is its exact words.
    public struct Pending: Decodable, Equatable, Identifiable, Sendable {
        public let id: String
        public let line: String
    }

    /// What the sheet and the ledger are given (GET /voice/night-shift).
    public struct Options: Decodable, Equatable, Sendable {
        public struct Caps: Decodable, Equatable, Sendable {
            public let hours: Double
            public let messages: Int
            public let notify: Bool

            public init(hours: Double = 8, messages: Int = 40, notify: Bool = false) {
                self.hours = hours
                self.messages = messages
                self.notify = notify
            }
        }

        /// The most a shift may be given. The daemon checks each one again.
        public struct Limits: Decodable, Equatable, Sendable {
            public let hours: Double
            public let messages: Int
            public let sessions: Int
            public let tasks: Int

            public init(hours: Double = 12, messages: Int = 200, sessions: Int = 8, tasks: Int = 5) {
                self.hours = hours
                self.messages = messages
                self.sessions = sessions
                self.tasks = tasks
            }
        }

        /// A session a task may go to. One that is not available is shown, disabled, with its why.
        public struct Session: Decodable, Equatable, Identifiable, Sendable {
            public let name: String
            public let harness: String?
            public let available: Bool
            public let why: String?
            public var id: String { name }
        }

        public let shift: Shift?
        public let history: [Summary]
        public let caps: Caps
        public let limits: Limits
        public let pending: Pending?
        public let sessions: [Session]

        public init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            shift = try c.decodeIfPresent(Shift.self, forKey: .shift)
            history = c.take(.history, or: [])
            caps = c.take(.caps, or: Caps())
            limits = c.take(.limits, or: Limits())
            pending = try? c.decodeIfPresent(Pending.self, forKey: .pending)
            sessions = c.take(.sessions, or: [])
        }

        enum CodingKeys: String, CodingKey { case shift, history, caps, limits, pending, sessions }
    }

    /// What the start sheet holds: a row per task, and the shift's caps.
    public struct Draft: Equatable, Sendable {
        /// One task: for a session on the voice, or for a new session with its agent and its folder.
        public struct Row: Equatable, Identifiable, Sendable {
            public let id: Int
            public var session: String?
            public var starts = false      // a new session instead of `session`
            public var harness: String?
            public var folder: String?     // a path from the New session options
            public var task = ""

            var words: String { task.trimmingCharacters(in: .whitespacesAndNewlines) }

            func ready(_ options: Options) -> Bool {
                guard !words.isEmpty else { return false }
                return starts ? harness != nil && folder != nil : options.sessions.contains { $0.name == session && $0.available }
            }

            var item: [String: any Sendable] {
                if starts { return ["start": ["harness": harness ?? "", "folder": folder ?? ""] as [String: String], "task": words] }
                return ["session": session ?? "", "task": words]
            }
        }

        public var rows: [Row] = []
        public var hours: Double = 8
        public var messages = 40
        public var notify = false
        private var made = 0

        public init() {}

        /// One empty row, and the Mac's caps, never past its limits.
        public init(_ options: Options, starting: NewSession.Options? = nil) {
            hours = min(options.caps.hours, options.limits.hours)
            messages = min(options.caps.messages, options.limits.messages)
            notify = options.caps.notify
            addRow(options, starting: starting)
        }

        /// A row for the first session that can take a task; with none on the voice, for a new session.
        public mutating func addRow(_ options: Options, starting: NewSession.Options? = nil) {
            var row = Row(id: made)
            made += 1
            row.session = options.sessions.first(where: \.available)?.name
            row.harness = starting?.harnesses.first(where: \.available)?.name
            row.folder = starting?.folders.first?.path
            row.starts = row.session == nil && row.harness != nil && row.folder != nil
            rows.append(row)
        }

        public func canAdd(_ options: Options) -> Bool { rows.count < options.limits.sessions * options.limits.tasks }

        /// Start is offered with at least one task written, and only when every written task has where to go: a session
        /// that can take it, or a new session's agent and folder. A row with no task is left out.
        public func canStart(_ options: Options) -> Bool {
            let written = rows.filter { !$0.words.isEmpty }
            return !written.isEmpty && written.allSatisfy { $0.ready(options) }
        }

        /// The request's body: the tasks in the sheet's order, and the caps.
        public var body: [String: any Sendable] {
            ["action": "start", "items": rows.filter { !$0.words.isEmpty }.map(\.item), "hours": hours, "messages": messages, "notify": notify]
        }
    }
}

private extension KeyedDecodingContainer {
    /// A key an older Mac does not send, or sends as null, is its default.
    func take<T: Decodable>(_ key: Key, or fallback: T) -> T {
        (try? decodeIfPresent(T.self, forKey: key)) ?? fallback
    }
}
