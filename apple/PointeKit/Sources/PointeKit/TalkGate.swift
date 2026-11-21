import Foundation

/// Push to talk on a client: which controls hold the microphone open. The daemon's gate is the rule (it drops audio
/// while closed, whatever a client sends); this model decides what the client sends and shows, and follows the daemon.
public struct TalkGate: Equatable, Sendable {
    /// What can hold the gate open: an on-screen control, a key in the window, the system-wide shortcut.
    public struct Input: Hashable, Sendable {
        public let name: String
        public init(_ name: String) { self.name = name }
        public static let ring = Input("ring")
        public static let caption = Input("caption")
        public static let key = Input("key")
        public static let shortcut = Input("shortcut")
    }

    /// Audio still sent after a release, so the last word is not cut. The daemon keeps the same tail.
    public static let tail: TimeInterval = 0.4
    /// The daemon closed the press by itself: held for 90 s, or no audio for 2 s.
    public static let closedByTheMac: Set<String> = ["held too long", "no audio"]

    public var mode = "always"  // the daemon's "microphone" setting: "always" or "ptt"
    public private(set) var held: Set<Input> = []
    public private(set) var toggled = false
    public private(set) var roomHeard = false  // a meeting is on: the daemon takes the room's audio without a press
    public private(set) var releasedAt: Date?
    /// The daemon's status showed this press open: only then can its "closed" be about this press, not an earlier one.
    public private(set) var confirmed = false

    public init() {}

    public var ptt: Bool { mode == "ptt" }
    public var isOpen: Bool { ptt && (toggled || !held.isEmpty) }

    /// Open while any hold is down: a second finger is not a new press.
    public mutating func press(_ input: Input, at now: Date = Date()) {
        guard ptt else { return }
        let was = isOpen
        held.insert(input)
        if !was { opened() }
    }

    /// The last event wins: letting go of the last hold closes, even when a toggle had opened it.
    public mutating func release(_ input: Input, at now: Date = Date()) {
        let was = isOpen
        guard held.remove(input) != nil, held.isEmpty else { return }
        toggled = false
        if was { closed(now) }
    }

    /// The last event wins: a toggle closes whatever holds it open, or opens it.
    public mutating func toggle(at now: Date = Date()) {
        guard ptt else { return }
        if isOpen {
            held = []
            toggled = false
            closed(now)
        } else {
            toggled = true
            opened()
        }
    }

    /// The daemon's word on the call link: a shortcut there pressed the gate, so this client sends as if its own press
    /// held it; said again for the state it is in, nothing changes.
    public mutating func set(open: Bool, at now: Date = Date()) {
        guard ptt, open != isOpen else { return }
        toggle(at: now)
    }

    /// What the talk control shows. This client's own press, which changes at the touch; the daemon's open gate (polled,
    /// so up to half a second behind) only while this client holds no press and has not just let one go.
    public func shows(macOpen: Bool) -> Bool {
        isOpen || (macOpen && releasedAt == nil)
    }

    /// The line when the daemon closed a press by itself, in the page's words (tests/test_ptt_modes.py holds both).
    public static func closedLine(_ why: String, style: TalkStyle) -> String {
        why == "held too long" ? "Talk closed after 90 s: \(style == .tap ? "tap" : "press") again" : "Talk closed: no audio reached the Mac"
    }

    /// Whether a chunk of microphone audio goes to the daemon now.
    public func sends(at now: Date = Date()) -> Bool {
        !ptt || roomHeard || isOpen || releasedAt.map { now.timeIntervalSince($0) < Self.tail } ?? false
    }

    /// The daemon's status. Returns why, when the daemon closed this press by itself; the client then closes too.
    public mutating func follow(_ status: API.PTTStatus?) -> String? {
        roomHeard = status?.room_heard == true
        guard let status, isOpen else { return nil }
        if status.open == true {
            confirmed = true
            return nil
        }
        guard confirmed, let why = status.closed_why, Self.closedByTheMac.contains(why) else { return nil }
        held = []
        toggled = false
        releasedAt = nil  // the daemon's gate is shut: no tail to send
        confirmed = false
        return why
    }

    /// A new call starts closed.
    public mutating func reset() {
        held = []
        toggled = false
        releasedAt = nil
        confirmed = false
    }

    private mutating func opened() {
        releasedAt = nil
        confirmed = false
    }

    private mutating func closed(_ now: Date) {
        releasedAt = now
        confirmed = false
    }

    /// The control message on the call's socket (protocol 3).
    public static func message(open: Bool, at: Date) -> String {
        Wire.json(["type": "ptt", "open": open, "at": Int(at.timeIntervalSince1970 * 1000)])
    }
}

/// A press is one message, as a voice message is: its words show as a draft until the press closes and the daemon sends
/// all of it as one turn (docs/design/push-to-talk-modes.md). The page says the same (tests/test_ptt_message.py).
public enum TalkDraft {
    public static let openLine = "Draft · not sent yet"
    public static let sendingLine = "Sending"

    /// The label over the live bubble; nil when the words are not a press's draft (always on, or an older daemon).
    public static func line(draft: Bool?, open: Bool) -> String? {
        guard draft == true else { return nil }
        return open ? openLine : sendingLine
    }
}

/// How the talk button is pressed, this device's choice (docs/design/push-to-talk-modes.md). The page offers the same
/// two (Settings → Microphone → Talk button); the daemon sees one press either way.
public enum TalkStyle: String, CaseIterable, Sendable {
    case hold, tap

    public static let key = "talkStyle"
    public static func stored(in defaults: UserDefaults = .standard) -> TalkStyle {
        defaults.string(forKey: key).flatMap(TalkStyle.init) ?? .hold
    }

    public var label: String { self == .tap ? "Tap to talk" : "Hold to talk" }
    /// The state line and the ring while the gate is open.
    public var talkingLine: String { self == .tap ? "Talking · tap to send" : "Talking" }
    /// The state line, then idle, right after a press closed: the send reads as taken.
    public static let sentLine = "Sent"
    public static let sentFor: TimeInterval = 0.6
    /// A press shorter than this in Hold mode heard no word: the line points at the other style.
    public static let shortPress: TimeInterval = 0.25
    public static let shortPressLine = "Hold to talk · or choose Tap to talk in Settings"
    public static let shortPressFor: TimeInterval = 2
    public var hint: String { self == .tap ? "Tap to start talking, tap again to send." : "Hold to talk. With VoiceOver, activate to start and again to stop." }
}
