import PointeKit
import Foundation

/// The state line, in one place: the call screen's title, and on the Mac the menu bar item's and the bubble's. The first
/// of these that holds is the line.
enum CallTitle {
    @MainActor
    static func line(phase: Call.State, reach: Reach, status: API.Status?, call: Call, macName: String, dumping: Bool, talking: Bool,
                     speaking: Bool, muted: Bool) -> String {
        switch phase {
        case .off: return ConnectCopy.offTitle(reach: reach, macOnACall: status?.connected == true)
        case .connecting: return ConnectCopy.connecting(macName)
        case .reconnecting: return "Reconnecting…"
        case .live:
            let writing = MuteChoice.writing(status: status, stored: false)  // muted: shown where it would have spoken
            // The turn was taken and nothing is said yet, or a session has the request (Thinking.swift).
            let waiting = ThinkingRule.phase(status: status, told: call.toldPhase)
            let thinking = waiting?.name == "thinking"
            if let refused = status?.key_refused ?? status?.vendor_fault { return refused.ears ? ConnectCopy.cannotHear : ConnectCopy.cannotAnswer }
            if status?.challenge?.on == true { return ChallengeCopy.state }
            if dumping { return BrainDumpCopy.state }
            if status?.hold != nil { return TurnsCopy.holding }
            if call.talk.ptt {
                if talking { return talkingLine(call) }
                if speaking { return MuteCopy.speaking }
                if writing { return MuteCopy.writing }
                if thinking { return ThinkingCopy.thinking }
                if let note = call.talkNote { return note }
                if let why = call.talkClosedWhy { return TalkGate.closedLine(why, style: call.talkStyle) }
                return call.talk.roomHeard ? "Meeting: room is heard · \(call.talkStyle.label.lowercased())" : call.talkStyle.label
            }
            if muted { return MicCopy.off }
            if speaking { return MuteCopy.speaking }
            if writing { return MuteCopy.writing }
            if thinking { return ThinkingCopy.thinking }
            if waiting?.name == "working", let session = waiting?.session { return ThinkingCopy.working(session) }
            return "Listening"
        }
    }

    /// A press opened by a toggle (Talk to Pointe, an AirPods press) has no finger to lift: on the iPhone the line says how
    /// it is sent, whatever the talk button's style (a tap on the mic sends it either way).
    @MainActor
    static func talkingLine(_ call: Call) -> String {
        #if os(iOS)
        if call.talk.toggled { return TalkStyle.tap.talkingLine }
        #endif
        return call.talkStyle.talkingLine
    }
}

/// What holds the call when the screen is not the whole app (the Mac app's menu bar item, bubble and shortcut): it hears
/// each status the screen fetched, and asks the screen to open a sheet or start something.
@MainActor
protocol CallShell: AnyObject {
    func polled(_ status: API.Status?, reach: Reach)
    var request: ShellRequest? { get }
    /// A demo's "Speaking…" line was skipped, in the window or by the shell's key: both stop showing it.
    var demoSkipped: Bool { get set }
}

/// One thing a menu or a shortcut asked the call screen for. `id` makes the same command twice two requests.
struct ShellRequest: Equatable {
    enum Command: Equatable { case settings, sessions, newSession, addSessions, brainDump, meeting, type, about, briefing, machines, phone, nightShift, approve, deny }
    let id: Int
    let command: Command
}
