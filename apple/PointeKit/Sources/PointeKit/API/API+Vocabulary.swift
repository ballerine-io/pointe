import Foundation

// The daemon's status and replies, as the page and the apps read them. Every field a newer daemon added is optional:
// an older daemon sends none of them and the status must still decode.

extension API {
    public struct DictionaryLearned: Decodable, Equatable, Hashable, Sendable {
        public let term: String
        public let at: Double

        public init(term: String, at: Double) {
            self.term = term
            self.at = at
        }
    }

    /// In every status poll: enough for the toast and the count.
    public struct DictionaryStatus: Decodable, Equatable, Sendable {
        public let count: Int?
        public let cap: Int?
        public let full: Bool?
        public let learn: Bool?
        public let learned_this_call: [DictionaryLearned]?
        public let problem: String?

        public init(count: Int? = nil, cap: Int? = nil, full: Bool? = nil, learn: Bool? = nil, learned_this_call: [DictionaryLearned]? = nil, problem: String? = nil) {
            self.count = count
            self.cap = cap
            self.full = full
            self.learn = learn
            self.learned_this_call = learned_this_call
            self.problem = problem
        }
    }

    public struct DictionaryEntry: Decodable, Equatable, Identifiable, Hashable, Sendable {
        public let term: String
        public let lang: String        // en, he, both
        public let source: String      // correction, manual, session
        public let hits: Int?
        public var id: String { term }

        public init(term: String, lang: String, source: String, hits: Int? = nil) {
            self.term = term
            self.lang = lang
            self.source = source
            self.hits = hits
        }
    }

    public struct DictionarySuggestion: Decodable, Equatable, Identifiable, Hashable, Sendable {
        public let term: String
        public let session: String
        public let lang: String?
        public var id: String { term }

        public init(term: String, session: String, lang: String? = nil) {
            self.term = term
            self.session = session
            self.lang = lang
        }
    }

    public struct DictionaryPage: Decodable, Equatable, Sendable {
        public let entries: [DictionaryEntry]
        public let suggestions: [DictionarySuggestion]?
        public let ignored: [String]?
        public let count: Int?
        public let cap: Int?
        public let full: Bool?
        public let learn: Bool?
        public let problem: String?

        public init(entries: [DictionaryEntry], suggestions: [DictionarySuggestion]? = nil, ignored: [String]? = nil, count: Int? = nil, cap: Int? = nil, full: Bool? = nil, learn: Bool? = nil, problem: String? = nil) {
            self.entries = entries
            self.suggestions = suggestions
            self.ignored = ignored
            self.count = count
            self.cap = cap
            self.full = full
            self.learn = learn
            self.problem = problem
        }
    }
}
