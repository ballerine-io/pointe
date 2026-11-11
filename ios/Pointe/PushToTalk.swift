import AppIntents
import SwiftUI

/// Push to talk, on the phone: which controls hold the microphone open. The Mac's gate is the rule (it drops audio while
/// closed, whatever the phone sends); this model decides what the phone sends and shows, and follows the Mac's word.
struct TalkGate: Equatable {
    /// The on-screen holds, and the toggles (an AirPods press, the Action button).
    enum Input: Hashable { case ring, caption }

    /// Audio still sent after a release, so the last word is not cut. The Mac keeps the same tail.
    static let tail: TimeInterval = 0.4
    /// The Mac closed the press by itself: held for 90 s, or no audio for 2 s.
    static let closedByTheMac: Set<String> = ["held too long", "no audio"]

    var mode = "always"  // the Mac's "microphone" setting: "always" or "ptt"
    private(set) var held: Set<Input> = []
    private(set) var toggled = false
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

    /// Whether a chunk of microphone audio goes to the Mac now.
    func sends(at now: Date = Date()) -> Bool {
        !ptt || isOpen || releasedAt.map { now.timeIntervalSince($0) < Self.tail } ?? false
    }

    /// The Mac's status. Returns why, when the Mac closed this press by itself; the phone then closes too.
    mutating func follow(_ status: API.PTTStatus?) -> String? {
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

/// The mic ring's push-to-talk side: what it shows, and what a press does.
struct RingTalk {
    let talking: Bool
    let press: () -> Void
    let release: () -> Void
    let toggle: () -> Void
}

extension View {
    /// Hold the ring to talk: open on touch down, closed on lift (a tap is a short press). VoiceOver's activate toggles.
    @ViewBuilder func ringTalk(_ talk: RingTalk?) -> some View {
        if let talk {
            simultaneousGesture(DragGesture(minimumDistance: 0)
                .onChanged { _ in if !talk.talking { talk.press() } }
                .onEnded { _ in talk.release() })
                .accessibilityLabel(talk.talking ? "Talking" : "Hold to talk")
                .accessibilityHint("Hold to talk. With VoiceOver, activate to start and again to stop.")
                .accessibilityAction { talk.toggle() }
                .sensoryFeedback(.impact(weight: .medium), trigger: talk.talking)
        } else {
            self
        }
    }

    /// Hold anywhere on the conversation to talk, after a short press so scrolling stays free.
    @ViewBuilder func holdToTalk(_ enabled: Bool, press: @escaping () -> Void, release: @escaping () -> Void) -> some View {
        if enabled {
            // A long press ends when it is recognised, not at the lift: the drag after it sees the finger come up.
            simultaneousGesture(LongPressGesture(minimumDuration: 0.35, maximumDistance: 12)
                .sequenced(before: DragGesture(minimumDistance: 0))
                .onChanged { value in if case .second(true, _) = value { press() } }
                .onEnded { value in if case .second(true, _) = value { release() } })
        } else {
            self
        }
    }
}

/// "Pointe: Talk" for the Action button and Shortcuts: starts or stops talking on the call that is up.
struct TalkIntent: AppIntent {
    static let title: LocalizedStringResource = "Talk"
    static let description = IntentDescription("Start or stop talking to Pointe, when the microphone is set to push to talk.")
    static let openAppWhenRun = false

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let call = Call.current, call.state == .live else { return .result(dialog: "Start a call in Pointe first.") }
        guard call.talk.ptt else { return .result(dialog: "Set the microphone to push to talk in Pointe first.") }
        call.talkToggle()
        return .result(dialog: call.talk.isOpen ? "Talking." : "Stopped.")
    }
}

struct PointeShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: TalkIntent(), phrases: ["\(.applicationName): Talk", "Talk to \(.applicationName)"],
                    shortTitle: "Talk", systemImageName: "mic.fill")
    }
}
