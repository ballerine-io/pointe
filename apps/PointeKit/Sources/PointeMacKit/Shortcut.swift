#if os(macOS)
import Foundation

/// A system-wide key combination: a virtual key code and Carbon's modifier mask (what `RegisterEventHotKey` takes).
public struct Shortcut: Codable, Equatable, Sendable {
    public var keyCode: UInt32
    public var modifiers: UInt32

    // Carbon's masks (HIToolbox/Events.h), so this file needs no Carbon import and can be tested anywhere on macOS.
    public static let command: UInt32 = 1 << 8, shift: UInt32 = 1 << 9, option: UInt32 = 1 << 11, control: UInt32 = 1 << 12

    public init(keyCode: UInt32, modifiers: UInt32) {
        self.keyCode = keyCode
        self.modifiers = modifiers
    }

    /// ⌃⌥Space: free on a stock Mac, and reachable with one hand.
    public static let standard = Shortcut(keyCode: 49, modifiers: control | option)
    public static let key = "pointe.shortcut"

    /// What a shortcut is for. Each has its own default and its own place in the defaults; no two may be the same keys.
    public enum Role: String, CaseIterable, Sendable {
        case talk, skip

        /// Skip is ⌃⌥S: the talk shortcut's modifiers, so the two sit under one hand; free on a stock Mac, and not one of
        /// the ⌃⌥ keys the common window managers take (the arrows, Return, C, D, E, F, G, T, U, I, J, K).
        public var standard: Shortcut {
            switch self {
            case .talk: Shortcut.standard
            case .skip: Shortcut(keyCode: 1, modifiers: Shortcut.control | Shortcut.option)
            }
        }

        public var key: String {
            switch self {
            case .talk: Shortcut.key
            case .skip: "pointe.shortcut.skip"
            }
        }

        /// As Settings names it.
        public var label: String {
            switch self {
            case .talk: "Talk shortcut"
            case .skip: "Skip shortcut"
            }
        }
    }

    /// The other role's keys: one combination can do one thing. Nil when `self` is free of `other`.
    public func clash(with other: Shortcut?, _ role: Role) -> String? {
        other == self ? "\(display) is the \(role.label.lowercased()). Choose another." : nil
    }

    public enum Problem: Equatable, Sendable {
        /// A key alone, or with Shift only, would be taken from every app while typing.
        case needsModifier
        /// macOS answers this one itself, so it would never arrive: the name of what owns it.
        case system(String)
    }

    /// The combinations macOS itself answers on a stock Mac. Registering them succeeds and then nothing arrives.
    static let taken: [Shortcut: String] = [
        Shortcut(keyCode: 49, modifiers: command): "Spotlight",
        Shortcut(keyCode: 49, modifiers: command | option): "Finder search",
        Shortcut(keyCode: 49, modifiers: control): "the input source switch",
        Shortcut(keyCode: 49, modifiers: control | command): "the emoji picker",
        Shortcut(keyCode: 48, modifiers: command): "the app switcher",
        Shortcut(keyCode: 12, modifiers: command): "Quit",
        Shortcut(keyCode: 13, modifiers: command): "Close",
        Shortcut(keyCode: 4, modifiers: command): "Hide",
        Shortcut(keyCode: 46, modifiers: command): "Minimize",
    ]

    public var problem: Problem? {
        if modifiers & (Self.command | Self.option | Self.control) == 0, !Self.functionKeys.contains(keyCode) { return .needsModifier }
        if let owner = Self.taken[self] { return .system(owner) }
        return nil
    }

    static let functionKeys: Set<UInt32> = [122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111, 105, 107, 113, 106, 64, 79, 80, 90]

    static let names: [UInt32: String] = [
        49: "Space", 36: "Return", 48: "Tab", 51: "Delete", 53: "Esc", 123: "←", 124: "→", 125: "↓", 126: "↑",
        122: "F1", 120: "F2", 99: "F3", 118: "F4", 96: "F5", 97: "F6", 98: "F7", 100: "F8", 101: "F9", 109: "F10", 103: "F11", 111: "F12",
        105: "F13", 107: "F14", 113: "F15", 106: "F16", 64: "F17", 79: "F18", 80: "F19", 90: "F20",
        0: "A", 11: "B", 8: "C", 2: "D", 14: "E", 3: "F", 5: "G", 4: "H", 34: "I", 38: "J", 40: "K", 37: "L", 46: "M", 45: "N",
        31: "O", 35: "P", 12: "Q", 15: "R", 1: "S", 17: "T", 32: "U", 9: "V", 13: "W", 7: "X", 16: "Y", 6: "Z",
        29: "0", 18: "1", 19: "2", 20: "3", 21: "4", 23: "5", 22: "6", 26: "7", 28: "8", 25: "9",
        50: "`", 27: "-", 24: "=", 33: "[", 30: "]", 42: "\\", 41: ";", 39: "'", 43: ",", 47: ".", 44: "/",
    ]

    /// "⌃⌥Space": the modifiers in the order macOS writes them, then the key.
    public var display: String {
        var out = ""
        if modifiers & Self.control != 0 { out += "⌃" }
        if modifiers & Self.option != 0 { out += "⌥" }
        if modifiers & Self.shift != 0 { out += "⇧" }
        if modifiers & Self.command != 0 { out += "⌘" }
        return out + (Self.names[keyCode] ?? "key \(keyCode)")
    }

    /// For VoiceOver: "Control Option Space".
    public var spoken: String {
        var words: [String] = []
        if modifiers & Self.control != 0 { words.append("Control") }
        if modifiers & Self.option != 0 { words.append("Option") }
        if modifiers & Self.shift != 0 { words.append("Shift") }
        if modifiers & Self.command != 0 { words.append("Command") }
        return (words + [Self.names[keyCode] ?? "key \(keyCode)"]).joined(separator: " ")
    }

    public static func stored(_ role: Role = .talk, in defaults: UserDefaults = .standard) -> Shortcut? {
        guard let data = defaults.data(forKey: role.key) else { return role.standard }
        return try? JSONDecoder().decode(Shortcut?.self, from: data)  // an explicit "none" is stored as null
    }

    public static func store(_ shortcut: Shortcut?, _ role: Role = .talk, in defaults: UserDefaults = .standard) {
        defaults.set(try? JSONEncoder().encode(shortcut), forKey: role.key)
    }
}

extension Shortcut: Hashable {}
#endif

#if os(macOS)
/// A second opinion on "is the shortcut still held", for the rare release that never arrives as an event (seen with
/// zero-length synthesized presses). Fed the key's state a few times a second while a press is open: it says "released"
/// only after the key was seen down at least once and then up `needed` times in a row. If the system never shows the
/// key down (the state cannot be read), it never speaks, so a real hold is never cut short.
public struct ReleaseWatch: Equatable, Sendable {
    public static let every: Duration = .milliseconds(100)
    private let needed: Int
    private var sawDown = false
    private var ups = 0

    public init(needed: Int = 3) { self.needed = needed }

    /// True when the press should be treated as released now.
    public mutating func sample(down: Bool) -> Bool {
        if down {
            sawDown = true
            ups = 0
            return false
        }
        guard sawDown else { return false }
        ups += 1
        return ups >= needed
    }
}
#endif
