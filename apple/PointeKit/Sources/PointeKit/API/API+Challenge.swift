import Foundation

// The daemon's status and replies, as the page and the apps read them. Every field a newer daemon added is optional:
// an older daemon sends none of them and the status must still decode.

extension API {
    public struct ChallengeItem: Decodable, Equatable, Hashable, Sendable {
        public let kind: String            // objection, rebuttal, verdict
        public let text: String
        public let at: Double?

        public init(kind: String, text: String, at: Double? = nil) {
            self.kind = kind
            self.text = text
            self.at = at
        }
    }

    /// On now, or the last one after it ended (`on` false) until a new one starts.
    public struct ChallengeStatus: Decodable, Equatable, Sendable {
        public var id: String
        public var on: Bool
        public let since: Double?
        public var ended_at: Double?
        public var plan: String?
        public let sessions: [String]?
        public let objections: Int?
        public let verdict: String?
        public let evidence: Int?
        public var items: [ChallengeItem]?

        public init(id: String, on: Bool, since: Double? = nil, ended_at: Double? = nil, plan: String? = nil, sessions: [String]? = nil, objections: Int? = nil, verdict: String? = nil, evidence: Int? = nil, items: [ChallengeItem]? = nil) {
            self.id = id
            self.on = on
            self.since = since
            self.ended_at = ended_at
            self.plan = plan
            self.sessions = sessions
            self.objections = objections
            self.verdict = verdict
            self.evidence = evidence
            self.items = items
        }
    }
}
