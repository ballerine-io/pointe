#if os(macOS)
import Foundation

/// The words for which keys a person needs: `vendors.WHAT_YOU_NEED`, `setups.WHY_KEYS` and `key_status`'s lines,
/// held to them by tests/test_key_setup.py. Keep each on one line in the form `static let name = "…"`.
public enum KeyCopy {
    public static let whatYouNeedTitle = "What do I need?"
    public static let whatYouNeed = "Any one of these is enough to start: (a) one Gemini key (free tier; about $0.70 to $0.95 a busy hour with billing on), (b) one OpenAI key (about $0.95 a busy hour), (c) Soniox + Anthropic API keys (about $1.20). Fastest and most accurate voice: Anthropic + Soniox + ElevenLabs (+ Gemini for the checker), about $1 a busy hour."
    public static let whyKeys = "Why its own keys? Pointe runs its own models next to Claude Code: the brain, the reader and the checker, the ears and the voice. Your Claude subscription (Pro or Max) runs Claude Code, but has no interface other apps can use, so Pointe's voice needs its own API key from console.anthropic.com, or one Gemini key. An API key is billed per use: about $1 for a busy hour of talk."
    public static let allFilled = "Every role is filled."
    public static let othersOptional = "The other keys are optional: not needed with your current keys."
    public static let noKey = "No model key yet."
    public static let inUse = "In use"
    public static let notUsed = "Saved, not used"
    public static let needed = "Needed"
    public static let optional = "Optional"
    public static let setupLabel = "Setup"
    public static let noSetup = "None chosen"
    public static let noSetupHow = "None chosen, so each role takes the first vendor with a key."
}

/// One row of `setups.SETUPS`, as the Mac app's menu shows it; tests/test_setups.py holds this list to it.
public struct SetupChoice: Identifiable, Equatable, Sendable {
    public let id: String
    public let name: String
    public let keys: [Vendor]
    public let optional: [Vendor]
    /// "voice": ears and mouth on this Mac; "all": every model on it.
    public let local: String
    public let short: String
    public let pickFor: String

    public static let all: [SetupChoice] = [
        SetupChoice(id: "free", name: "Free start", keys: [.gemini], optional: [], local: "", short: "One Gemini key. Free to try; slower replies, headphones.", pickFor: "trying Pointe at no cost"),
        SetupChoice(id: "openai", name: "One OpenAI key", keys: [.openai], optional: [], local: "", short: "One OpenAI key. Headphones; weakest audio result.", pickFor: "people who already pay for OpenAI"),
        SetupChoice(id: "two", name: "Two keys", keys: [.soniox, .anthropic], optional: [], local: "", short: "Soniox and Anthropic. Best ears, works on speakers.", pickFor: "the best ears with two accounts, on laptop speakers"),
        SetupChoice(id: "full", name: "Fastest and most accurate voice", keys: [.anthropic, .soniox, .elevenlabs, .gemini], optional: [], local: "", short: "Anthropic, Soniox, ElevenLabs, Gemini. Fastest replies, best ears and voice.", pickFor: "daily use"),
        SetupChoice(id: "voice-local", name: "Voice stays on your Mac", keys: [.anthropic], optional: [.gemini], local: "voice", short: "One Anthropic key; ears and voice on the Mac. No audio leaves it.", pickFor: "confidential work where text may leave the Mac but your voice may not"),
        SetupChoice(id: "local", name: "Fully local", keys: [], optional: [], local: "all", short: "No key. Every model on the Mac; slow, English only.", pickFor: "work where nothing may leave the Mac, on a 32 GB Mac"),
    ]

    public static func named(_ id: String?) -> SetupChoice? { all.first { $0.id == id } }
}

/// Which roles the keys in the Keychain fill, as the daemon fills them: `vendors.filled` and `vendors.key_status`, whose
/// orders tests/test_key_setup.py holds this to. With a setup chosen, only its vendors count, a key it uses and lacks
/// is needed and every other key optional. With none, a missing key is optional while every role is filled; only an
/// empty role is a problem, and it names the one key that fills it.
public struct KeyPlan: Equatable, Sendable {
    public enum State: Equatable, Sendable { case inUse, notUsed, needed, optional }

    static let roles: [(String, [Vendor])] = [
        ("brain", [.anthropic, .gemini, .openai]),
        ("reader", [.anthropic, .gemini, .openai]),
        ("checker", [.gemini, .anthropic, .openai]),
        ("ears", [.soniox, .gemini, .openai, .elevenlabs]),
        ("mouth", [.elevenlabs, .gemini, .soniox, .openai]),
    ]
    static let fixOrder: [Vendor] = [.soniox, .anthropic, .elevenlabs, .gemini, .openai]
    static let roleWords = ["brain": "think", "reader": "read your sessions", "checker": "check each send", "ears": "hear you", "mouth": "speak"]

    public let present: Set<Vendor>
    public let setup: SetupChoice?
    /// The roles no key fills, in the daemon's order.
    public let empty: [String]
    /// The keys to add: the chosen setup's missing ones, or with none chosen the one key that fills every empty role.
    public let needed: [Vendor]

    public init(present: Set<Vendor>, setup: SetupChoice? = nil) {
        self.present = present
        self.setup = setup
        empty = Self.empty(present, setup)
        if let setup {
            needed = setup.keys.filter { !present.contains($0) }
        } else if empty.isEmpty {
            needed = []
        } else if present.isEmpty {
            needed = [.gemini]
        } else {
            needed = Self.fixOrder.first { Self.empty(present.union([$0]), nil).isEmpty }.map { [$0] } ?? []
        }
    }

    /// The vendor filling each role: nil where none, and none of the keyed vendors where the role runs on this Mac.
    static func filler(_ present: Set<Vendor>, _ setup: SetupChoice?, _ role: String, _ order: [Vendor]) -> (Vendor?, Bool) {
        if setup?.local == "all" || (setup?.local == "voice" && (role == "ears" || role == "mouth")) { return (nil, true) }
        let allowed = setup.map { present.intersection($0.keys + $0.optional) } ?? present
        return (order.first(where: allowed.contains), false)
    }

    static func empty(_ present: Set<Vendor>, _ setup: SetupChoice?) -> [String] {
        roles.filter { role, order in let (v, local) = filler(present, setup, role, order); return v == nil && !local }.map(\.0)
    }

    public var fix: Vendor? { needed.first }
    public var ready: Bool { empty.isEmpty && needed.isEmpty }

    public func state(_ vendor: Vendor) -> State {
        if present.contains(vendor) {
            return Self.roles.contains { Self.filler(present, setup, $0.0, $0.1).0 == vendor } ? .inUse : .notUsed
        }
        return needed.contains(vendor) ? .needed : .optional
    }

    /// The one line above the keys: all filled, nothing yet, or what is missing and the key that fixes it.
    public var line: String {
        let head = setup.map { "Setup: \($0.name). " } ?? ""
        if setup != nil, !needed.isEmpty {
            return head + "It needs \(Self.join(needed.map { Self.article($0.shortName) }, "and")) key: pointe key \(needed[0].rawValue)."
        }
        if ready {
            return head + (Vendor.allCases.contains { state($0) == .optional } ? "\(KeyCopy.allFilled) \(KeyCopy.othersOptional)" : KeyCopy.allFilled)
        }
        if present.isEmpty { return "\(KeyCopy.noKey) \(KeyCopy.whatYouNeed)" }
        return "Pointe cannot \(Self.join(empty.compactMap { Self.roleWords[$0] }, "or")) yet: add \(Self.article(fix?.shortName ?? "")) key."
    }

    static func join(_ words: [String], _ last: String) -> String {
        words.count == 1 ? words[0] : words.dropLast().joined(separator: ", ") + " \(last) " + words.last!
    }

    static func article(_ name: String) -> String { "\("AEIOU".contains(name.prefix(1)) ? "an" : "a") \(name)" }
}

extension Vendor {
    /// The vendor as the key lines name it (`vendors.NAMES`): "Gemini", where the row's label says "Google Gemini".
    public var shortName: String {
        switch self {
        case .gemini: "Gemini"
        case .openai: "OpenAI"
        case .anthropic: "Anthropic"
        case .soniox: "Soniox"
        case .elevenlabs: "ElevenLabs"
        }
    }
}
#endif
