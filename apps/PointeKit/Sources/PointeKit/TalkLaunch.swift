import Foundation

/// "Talk to Pointe" from outside the app: the Control (Control Center, the Lock Screen, the Action button), the Home Screen
/// widget, Siri and Back Tap (docs/features/push-to-talk.md, "On the iPhone, from outside the app"). One press opens
/// Pointe on the call to the orchestrator, talking; the next press, or a tap on the mic, sends. These are the rules, with
/// no I/O: the app (PointeUI's PhoneTalk) carries them out, and the intents (apps/ios/PointeShared) only hand the press over.
///
/// The press opens the app rather than recording in the background: a background start waited for iOS to launch the
/// app (about 9 s in the simulator), depended on a Live Activity being allowed, and left Send in the Dynamic Island.
/// In front, the microphone starts at once, Send is the mic under your thumb, and a locked iPhone asks to unlock first.
///
/// A press never approves anything: the steps below dial, change the mode, open or close the push-to-talk gate and hang
/// up. Approving stays where it is, a tap behind Face ID or a spoken yes behind the voice lock (SECURITY.md).
public enum TalkLaunch {
    /// The call as the phone sees it (PointeUI's `Call.State`).
    public enum Phase: String, Codable, Sendable { case off, connecting, live, reconnecting }

    /// What the phone knows when a press arrives.
    public struct Now: Equatable, Sendable {
        public var outside: Bool    // Settings: "Talk from outside the app"
        public var paired: Bool
        public var call: Phase
        public var ptt: Bool        // the Mac's microphone setting is push to talk
        public var pressOpen: Bool

        public init(outside: Bool = true, paired: Bool = true, call: Phase = .off, ptt: Bool = true, pressOpen: Bool = false) {
            self.outside = outside
            self.paired = paired
            self.call = call
            self.ptt = ptt
            self.pressOpen = pressOpen
        }
    }

    public enum Step: Equatable, Sendable {
        case start      // no call: dial, put Pointe in Orchestrator mode, open a press
        case open       // a call in push to talk and no press: Orchestrator mode, and open one
        case send       // a press is open: close it, and the Mac sends what it heard as one turn
        case wait       // the call is being dialled: a second press changes nothing
        case refuse(Why)
    }

    public enum Why: Equatable, Sendable {
        case notPaired
        case noCall          // the setting is off: a press only talks on a call already up, as before 1.24
        case alwaysOn        // a press on a live call whose microphone is Always on: it is already listening
        case failed(String)  // the call did not come up: the call screen's own reason
    }

    /// The Action button, the Control, the widget, Siri: the same press.
    public static func press(_ now: Now) -> Step {
        switch now.call {
        case .connecting, .reconnecting: return .wait
        case .live:
            guard now.ptt else { return .refuse(.alwaysOn) }  // never a hang-up: a stray press must not end a call
            return now.pressOpen ? .send : .open
        case .off:
            if !now.paired { return .refuse(.notPaired) }
            return now.outside ? .start : .refuse(.noCall)
        }
    }

    /// The Live Activity's Send: closes a press that is open, and does nothing otherwise (it may be pressed late).
    public static func send(_ now: Now) -> Step {
        now.call == .live && now.ptt && now.pressOpen ? .send : .wait
    }

    /// A press is a press to the orchestrator, on a new call or one already up. Only Session mode is changed: a challenge
    /// or anything else the Mac is in stays as it is.
    public static func orchestrates(mode: String?) -> Bool { mode == "session" }

    /// How long a press waits for the call to come up before it says why not.
    public static let dialFor: TimeInterval = 10
}

/// What the Live Activity shows: one of these kinds decides its buttons, the words come with it.
public struct TalkActivityState: Codable, Hashable, Sendable {
    public enum Kind: String, Codable, Sendable {
        case connecting  // Cancel
        case talking     // a press is open: Send, Cancel
        case ready       // push to talk, no press: Talk, Hang up
        case listening   // Always on: Hang up
        case ended       // the call is over; the activity goes
    }

    public var kind: Kind
    public var title: String
    public var detail: String
    public var needs: Int
    public var mac: String

    public init(kind: Kind, title: String, detail: String, needs: Int, mac: String) {
        self.kind = kind
        self.title = title
        self.detail = detail
        self.needs = needs
        self.mac = mac
    }

    /// From the call: `note` is the line right after a press closed ("Sent"), as the call screen shows it.
    public static func of(call: TalkLaunch.Phase, ptt: Bool, pressOpen: Bool, speaking: Bool, note: String?, needs: Int,
                          mac: String, problem: String? = nil) -> TalkActivityState {
        func make(_ kind: Kind, _ title: String, _ detail: String) -> TalkActivityState {
            TalkActivityState(kind: kind, title: title, detail: detail, needs: needs, mac: mac)
        }
        switch call {
        case .off: return make(.ended, TalkLaunchCopy.ended, problem ?? TalkLaunchCopy.nothingSent)
        case .connecting: return make(.connecting, TalkLaunchCopy.calling(mac), TalkLaunchCopy.orchestrator)
        case .reconnecting: return make(.connecting, TalkLaunchCopy.reconnecting, TalkLaunchCopy.orchestrator)
        case .live:
            if !ptt { return make(.listening, speaking ? TalkLaunchCopy.speaking : TalkLaunchCopy.listening, TalkLaunchCopy.alwaysOnDetail) }
            if pressOpen { return make(.talking, TalkLaunchCopy.talking, TalkLaunchCopy.talkingDetail) }
            return make(.ready, speaking ? TalkLaunchCopy.speaking : note ?? TalkLaunchCopy.ready, TalkLaunchCopy.readyDetail)
        }
    }
}

/// The words, in the app's terms: "Talking · tap to send" is the call screen's line for an open press in Tap to talk
/// (TalkStyle in PointeUI), "need you" its count of sessions waiting, "Hang up" its button. Keep each string on one line.
public enum TalkLaunchCopy {
    public static let name = "Talk to Pointe"
    public static let controlAbout = "Opens Pointe talking to the orchestrator. Press again, or tap the mic, to send."
    public static let widgetAbout = "One tap opens Pointe talking to the orchestrator."
    public static let setting = "Talk from outside the app"
    public static let settingFooter = "The Talk to Pointe control and widget, the Action button, Siri and Back Tap open Pointe talking to the orchestrator, calling your Mac first if no call is up. Press again, or tap the mic, to send. Off: they open Pointe and talk only on a call already up."

    // the Live Activity
    public static let talking = "Talking · tap to send"
    public static let talkingDetail = "Orchestrator"
    public static let ready = "On a call"
    public static let readyDetail = "Press again to talk"
    public static let listening = "Listening"
    public static let speaking = "Speaking"
    public static let alwaysOnDetail = "Always on"
    public static let reconnecting = "Reconnecting…"
    public static let orchestrator = "Orchestrator"
    public static let ended = "Call ended"
    public static let nothingSent = "Nothing was sent"
    public static let send = "Send"
    public static let cancel = "Cancel"
    public static let talk = "Talk"
    public static let hangUp = "Hang up"
    public static func calling(_ mac: String) -> String { "Calling \(mac)…" }

    // what a press says back (Siri reads it; the Action button shows it)
    public static let talkingNow = "Talking to the orchestrator. Press again, or tap the mic, to send."
    public static let sent = "Sent."
    public static let listeningNow = "Listening. Microphone is Always on."
    public static let dialling = "Connecting…"
    public static let cancelled = "Cancelled: nothing was sent."
    public static let hungUp = "Hung up."
    public static let notPaired = "Pair this iPhone with your Mac in Pointe first."
    public static let noCall = "Talk from outside the app is off in Pointe's settings: tap Connect to call."
    public static let alwaysOn = "Microphone is Always on: Pointe is already listening."
    public static func failed(_ why: String) -> String { "The call did not start: \(why)" }

    public static func said(_ why: TalkLaunch.Why) -> String {
        switch why {
        case .notPaired: notPaired
        case .noCall: noCall
        case .alwaysOn: alwaysOn
        case .failed(let reason): failed(reason)
        }
    }

    // the Home Screen widget
    public static let setUp = "Open Pointe once to set this up"
    public static let off = "Off in Pointe's settings"
    public static let pair = "Pair with your Mac in Pointe"
    public static let pairAgain = "Pair this phone again"
    public static func reachable(_ mac: String) -> String { "\(mac) is reachable" }
    public static func away(_ mac: String) -> String { "\(mac) is not reachable" }
    public static func onACall(_ mac: String) -> String { "On a call with \(mac)" }
    public static let nothingNeedsYou = "Nothing needs you"
    public static func needYou(_ n: Int) -> String { "\(n) need\(n == 1 ? "s" : "") you" }

    /// The widget's line about the Mac, from the last thing the app saw; nil with nothing seen (none yet, or a build
    /// without the app group, as on a free Personal Team): the widget is then only its button, with no status.
    public static func line(_ s: TalkSnapshot?) -> String? {
        guard let s else { return nil }
        if !s.outside { return off }
        if !s.paired { return pair }
        switch s.reach {
        case .rejected: return pairAgain
        case .unreachable: return away(s.mac)
        case .ok: return s.call == .off ? reachable(s.mac) : onACall(s.mac)
        }
    }

    /// The widget's second line: nil when there is nothing to count (no pairing, no answer).
    public static func needs(_ s: TalkSnapshot?) -> String? {
        guard let s, s.outside, s.paired, s.reach == .ok else { return nil }
        return s.needs > 0 ? needYou(s.needs) : nothingNeedsYou
    }
}

/// A press from outside, handed to the app. Registered by the iPhone app at launch (PointeBoot); the intents call it.
/// It runs in the app's process, with the app in front: the press opens it (openAppWhenRun).
@MainActor
public protocol TalkLauncher: AnyObject {
    /// The Action button, the Control, the widget, Siri.
    func press() async -> TalkOutcome
    /// The Live Activity's Send.
    func send() async -> TalkOutcome
    /// The Live Activity's Cancel and Hang up: the call ends, and a press still open is never sent.
    func cancel() async -> TalkOutcome
}

public struct TalkOutcome: Equatable, Sendable {
    public let said: String

    public init(_ said: String) { self.said = said }

    public static func refused(_ why: TalkLaunch.Why) -> TalkOutcome { TalkOutcome(TalkLaunchCopy.said(why)) }
}

@MainActor
public enum TalkLaunchers {
    public static var current: (any TalkLauncher)?
}
