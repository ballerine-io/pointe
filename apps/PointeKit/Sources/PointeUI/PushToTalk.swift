import SwiftUI

/// Push to talk, on the phone: which controls hold the microphone open. The Mac's gate is the rule (it drops audio while
/// closed, whatever the phone sends); this model decides what the phone sends and shows, and follows the Mac's word.
struct TalkGate: Equatable {
    /// The on-screen holds, and the toggles (an AirPods press, the Action button).
    enum Input: Hashable { case ring, caption, shortcut }  // the mic, the conversation, and on the Mac the talk shortcut or the bubble

    /// Audio still sent after a release, so the last word is not cut. The Mac keeps the same tail.
    static let tail: TimeInterval = 0.4
    /// The Mac closed the press by itself: held for 90 s, or no audio for 2 s.
    static let closedByTheMac: Set<String> = ["held too long", "no audio"]

    var mode = "always"  // the Mac's "microphone" setting: "always" or "ptt"
    private(set) var held: Set<Input> = []
    private(set) var toggled = false
    private(set) var roomHeard = false  // a meeting is on: the Mac takes the room's audio without a press
    private(set) var releasedAt: Date?
    /// The Mac's status showed this press open: only then can its "closed" be about this press, not an earlier one.
    private(set) var confirmed = false

    var ptt: Bool { mode == "ptt" }
    var isOpen: Bool { ptt && (toggled || !held.isEmpty) }

    /// Open while any hold is down: a second finger is not a new press.
    mutating func press(_ input: Input, at now: Date = Date()) {
        guard ptt else { return }
        let was = isOpen
        held.insert(input)
        if !was { opened() }
    }

    /// The last event wins: letting go of the last hold closes, even when a toggle had opened it.
    mutating func release(_ input: Input, at now: Date = Date()) {
        let was = isOpen
        guard held.remove(input) != nil, held.isEmpty else { return }
        toggled = false
        if was { closed(now) }
    }

    /// The last event wins: a toggle closes whatever holds it open, or opens it.
    mutating func toggle(at now: Date = Date()) {
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

    /// The Mac's word on the call link: a system-wide shortcut there pressed the gate, so this phone sends as if its own
    /// press held it; said again for the state it is in, nothing changes.
    mutating func set(open: Bool, at now: Date = Date()) {
        guard ptt, open != isOpen else { return }
        toggle(at: now)
    }

    /// What the ring shows. This phone's own press, which changes at the touch; the Mac's open gate (polled, so up to
    /// half a second behind) only while this phone holds no press and has not just let one go. Taking the Mac's word
    /// first kept the ring orange after a lift and swallowed a press made inside that lag.
    func shows(macOpen: Bool) -> Bool {
        isOpen || (macOpen && releasedAt == nil)
    }

    /// The line when the Mac closed a press by itself, in the page's words (tests/test_ptt_modes.py holds both).
    static func closedLine(_ why: String, style: TalkStyle) -> String {
        why == "held too long" ? "Talk closed after 90 s: \(style == .tap ? "tap" : "press") again" : "Talk closed: no audio reached the Mac"
    }

    /// Whether a chunk of microphone audio goes to the Mac now.
    func sends(at now: Date = Date()) -> Bool {
        !ptt || roomHeard || isOpen || releasedAt.map { now.timeIntervalSince($0) < Self.tail } ?? false
    }

    /// The Mac's status. Returns why, when the Mac closed this press by itself; the phone then closes too.
    mutating func follow(_ status: API.PTTStatus?) -> String? {
        roomHeard = status?.room_heard == true
        guard let status, isOpen else { return nil }
        if status.open == true {
            confirmed = true
            return nil
        }
        guard confirmed, let why = status.closed_why, Self.closedByTheMac.contains(why) else { return nil }
        held = []
        toggled = false
        releasedAt = nil  // the Mac's gate is shut: no tail to send
        confirmed = false
        return why
    }

    /// A new call starts closed.
    mutating func reset() {
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
    static func message(open: Bool, at: Date) -> String {
        let body: [String: Any] = ["type": "ptt", "open": open, "at": Int(at.timeIntervalSince1970 * 1000)]
        let data = (try? JSONSerialization.data(withJSONObject: body, options: [.sortedKeys])) ?? Data()
        return String(data: data, encoding: .utf8) ?? ""
    }
}

/// A press is one message, as a voice message is: its words show as a draft until the press closes and the Mac sends
/// all of it as one turn (docs/design/push-to-talk-modes.md). The page says the same (tests/test_ptt_message.py).
enum TalkDraft {
    static let openLine = "Draft · not sent yet"
    static let sendingLine = "Sending"

    /// The label over the live bubble; nil when the words are not a press's draft (always on, or an older Mac).
    static func line(draft: Bool?, open: Bool) -> String? {
        guard draft == true else { return nil }
        return open ? openLine : sendingLine
    }
}

/// How the talk button is pressed, this device's choice (docs/design/push-to-talk-modes.md). The page offers the same two
/// (Settings → Microphone → Talk button); the daemon sees one press either way.
enum TalkStyle: String, CaseIterable {
    case hold, tap

    static let key = "talkStyle"
    static func stored(in defaults: UserDefaults = .standard) -> TalkStyle {
        defaults.string(forKey: key).flatMap(TalkStyle.init) ?? .hold
    }

    var label: String { self == .tap ? "Tap to talk" : "Hold to talk" }
    /// The state line and the ring while the gate is open.
    var talkingLine: String { self == .tap ? "Talking · tap to send" : "Talking" }
    /// The state line, then idle, right after a press closed: the send reads as taken.
    static let sentLine = "Sent"
    static let sentFor: TimeInterval = 0.6
    /// A press shorter than this in Hold mode heard no word: the line points at the other style.
    static let shortPress: TimeInterval = 0.25
    static let shortPressLine = "Hold to talk · or choose Tap to talk in Settings"
    static let shortPressFor: TimeInterval = 2
    var hint: String { self == .tap ? "Tap to start talking, tap again to send." : "Hold to talk. With VoiceOver, activate to start and again to stop." }
}

/// The mic ring's push-to-talk side: what it shows, and what a press does.
struct RingTalk {
    let talking: Bool
    let style: TalkStyle
    let press: (TimeInterval) -> Void   // when the finger came down, on the audio clock (systemUptime)
    let release: () -> Void
    let toggle: (TimeInterval) -> Void

    /// A touch's time on the audio clock: the press sends the audio from then on. SwiftUI gives it as a date that is the
    /// event's uptime counted from 2001 (measured on the simulator: read as a wall-clock date, the touch was 25 years
    /// back); a wall-clock date is taken too, should that change. Anything else is now.
    static func uptime(of date: Date, now: Date = Date(), uptime: TimeInterval = ProcessInfo.processInfo.systemUptime) -> TimeInterval {
        let ago = now.timeIntervalSince(date)
        if ago >= 0 && ago < 60 { return uptime - ago }
        let raw = date.timeIntervalSinceReferenceDate
        return raw <= uptime && uptime - raw < 60 ? raw : uptime
    }
}

/// Hold to talk: open on touch down, closed on lift (a tap is a short press). Tap to talk: touch down toggles, the lift
/// does nothing. Either way the first touch acts at once, before any word from the Mac. VoiceOver's activate toggles.
private struct RingTalkModifier: ViewModifier {
    let talk: RingTalk
    @State private var down = false

    func body(content: Content) -> some View {
        content
            .simultaneousGesture(DragGesture(minimumDistance: 0)
                .onChanged { value in
                    guard !down else { return }
                    down = true
                    let touched = RingTalk.uptime(of: value.time)
                    talk.style == .tap ? talk.toggle(touched) : talk.press(touched)  // a second finger is not a new press
                }
                .onEnded { _ in
                    down = false
                    if talk.style == .hold { talk.release() }
                })
            .accessibilityLabel(talk.talking ? "Talking" : talk.style.label)
            .accessibilityHint(talk.style.hint)
            .accessibilityAction { talk.toggle(ProcessInfo.processInfo.systemUptime) }
            .sensoryFeedback(.impact(weight: .medium), trigger: talk.talking)
    }
}

extension View {
    @ViewBuilder func ringTalk(_ talk: RingTalk?) -> some View {
        if let talk { modifier(RingTalkModifier(talk: talk)) } else { self }
    }

    /// Talk from anywhere on the conversation, after a short press so scrolling stays free: a hold in Hold mode, a toggle
    /// in Tap mode.
    @ViewBuilder func holdToTalk(_ enabled: Bool, style: TalkStyle, press: @escaping () -> Void, release: @escaping () -> Void,
                                 toggle: @escaping () -> Void) -> some View {
        if enabled {
            modifier(HoldToTalkModifier(style: style, press: press, release: release, toggle: toggle))
        } else {
            self
        }
    }
}

/// The conversation's press. The scroll view under it can end the gesture without its onEnded (iOS 26, a press that does
/// not move): a release tied to onEnded never came and the gate stayed open. A GestureState goes back to false however
/// the gesture ends, so the press and its release, or one toggle, follow that state.
private struct HoldToTalkModifier: ViewModifier {
    let style: TalkStyle
    let press: () -> Void
    let release: () -> Void
    let toggle: () -> Void
    @GestureState private var held = false

    @ViewBuilder func body(content: Content) -> some View {
        if style == .tap {
            // A toggle needs no lift: it happens when the long press is recognised. Tied to the held state below, the
            // second press toggled nothing on iOS 26, where the scroll view never ended the first press's sequence.
            content.simultaneousGesture(LongPressGesture(minimumDuration: 0.35, maximumDistance: 12).onEnded { _ in toggle() })
        } else {
            content
                // A long press ends when it is recognised, not at the lift: the drag after it sees the finger come up.
                .simultaneousGesture(LongPressGesture(minimumDuration: 0.35, maximumDistance: 12)
                    .sequenced(before: DragGesture(minimumDistance: 0))
                    .updating($held) { value, state, _ in if case .second(true, _) = value { state = true } })
                .onChange(of: held) { _, now in now ? press() : release() }
        }
    }
}
