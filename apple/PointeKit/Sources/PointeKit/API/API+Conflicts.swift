import Foundation

// The daemon's status and replies, as the page and the apps read them. Every field a newer daemon added is optional:
// an older daemon sends none of them and the status must still decode.

extension API {
    public struct Conflict: Decodable, Equatable, Identifiable, Sendable {
        public let id: String
        public let a: String
        public let b: String
        public let agent_a: String?
        public let agent_b: String?
        public let claim_a: String
        public let claim_b: String
        public let at_a: Double?
        public let at_b: Double?
        public let why: String?
        public let severity: String?        // high, normal
        public let branches: Branches?      // only when the two are on different branches
        public var asked: [String]?         // "a", "b": the sides already asked

        public func name(_ side: String) -> String { side == "a" ? a : b }
        public func wasAsked(_ side: String) -> Bool { asked?.contains(side) == true }

        public init(id: String, a: String, b: String, agent_a: String? = nil, agent_b: String? = nil, claim_a: String, claim_b: String, at_a: Double? = nil, at_b: Double? = nil, why: String? = nil, severity: String? = nil, branches: Branches? = nil, asked: [String]? = nil) {
            self.id = id
            self.a = a
            self.b = b
            self.agent_a = agent_a
            self.agent_b = agent_b
            self.claim_a = claim_a
            self.claim_b = claim_b
            self.at_a = at_a
            self.at_b = at_b
            self.why = why
            self.severity = severity
            self.branches = branches
            self.asked = asked
        }
    }

    public struct Branches: Decodable, Equatable, Sendable {
        public let a: String
        public let b: String

        public init(a: String, b: String) {
            self.a = a
            self.b = b
        }
    }
}
