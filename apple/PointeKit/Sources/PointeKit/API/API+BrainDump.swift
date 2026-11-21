import Foundation

// The daemon's status and replies, as the page and the apps read them. Every field a newer daemon added is optional:
// an older daemon sends none of them and the status must still decode.

extension API {
    public struct Thought: Decodable, Equatable, Hashable, Sendable {
        public let text: String
        public let at: Double?

        public init(text: String, at: Double? = nil) {
            self.text = text
            self.at = at
        }
    }

    /// The structured prompt: the sections, and the text that is shown and sent (the text wins once edited).
    public struct DumpPrompt: Decodable, Equatable, Sendable {
        public var goal: String?
        public var context: [String]?
        public var constraints: [String]?
        public var open_questions: [String]?
        public var text: String

        public init(goal: String? = nil, context: [String]? = nil, constraints: [String]? = nil, open_questions: [String]? = nil, text: String) {
            self.goal = goal
            self.context = context
            self.constraints = constraints
            self.open_questions = open_questions
            self.text = text
        }
    }

    /// Where Send goes unless the user picks another (braindump.send_to): the routing when the dump started. `gone`: the
    /// pinned session that left, so the default fell back to the orchestrator.
    public struct DumpSendTo: Decodable, Equatable, Sendable {
        public var orchestrator: Bool
        public var session: String?
        public var gone: String?

        public init(orchestrator: Bool, session: String? = nil, gone: String? = nil) {
            self.orchestrator = orchestrator
            self.session = session
            self.gone = gone
        }
    }

    /// Dumping, structuring, or in review; nil when there is none.
    public struct BrainDump: Decodable, Equatable, Sendable {
        public var id: String
        public var state: String            // dumping | structuring | review
        public let since: Double?
        public var thoughts: [Thought]
        public var dropped: Int?
        public var prompt: DumpPrompt?
        public var target: String?          // the session named by voice for the send
        public var problem: String?         // why the last action was refused
        public var resumed: Bool?           // left from a dropped call or the last run
        public var fallback: Bool?          // the model could not structure it: the prompt is the thoughts as said
        public var send_to: DumpSendTo?     // nil from a Mac before 1.7, which cannot send to the orchestrator

        public var isDumping: Bool { state != "review" }
        public var inReview: Bool { state == "review" && prompt != nil }

        public init(id: String, state: String, since: Double? = nil, thoughts: [Thought], dropped: Int? = nil, prompt: DumpPrompt? = nil, target: String? = nil, problem: String? = nil, resumed: Bool? = nil, fallback: Bool? = nil, send_to: DumpSendTo? = nil) {
            self.id = id
            self.state = state
            self.since = since
            self.thoughts = thoughts
            self.dropped = dropped
            self.prompt = prompt
            self.target = target
            self.problem = problem
            self.resumed = resumed
            self.fallback = fallback
            self.send_to = send_to
        }
    }
}
