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
            if let refused = status?.key_refused ?? status?.vendor_fault { return refused.ears ? ConnectCopy.cannotHear : ConnectCopy.cannotAnswer }
            if status?.challenge?.on == true { return ChallengeCopy.state }
            if dumping { return BrainDumpCopy.state }
            if status?.hold != nil { return TurnsCopy.holding }
            if call.talk.ptt {
                if talking { return call.talkStyle.talkingLine }
                if speaking { return "Speaking" }
                if let note = call.talkNote { return note }
                if let why = call.talkClosedWhy { return TalkGate.closedLine(why, style: call.talkStyle) }
                return call.talk.roomHeard ? "Meeting: room is heard · \(call.talkStyle.label.lowercased())" : call.talkStyle.label
            }
            return muted ? "Muted" : speaking ? "Speaking" : "Listening"
        }
    }
}

/// What holds the call when the screen is not the whole app (the Mac app's menu bar item, bubble and shortcut): it hears
/// each status the screen fetched, and asks the screen to open a sheet or start something.
@MainActor
protocol CallShell: AnyObject {
    func polled(_ status: API.Status?, reach: Reach)
    var request: ShellRequest? { get }
}

/// One thing a menu or a shortcut asked the call screen for. `id` makes the same command twice two requests.
struct ShellRequest: Equatable {
    enum Command: Equatable { case settings, sessions, newSession, addSessions, brainDump, meeting, type, about, briefing, machines, phone, nightShift }
    let id: Int
    let command: Command
}
