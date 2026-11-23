import Foundation

/// The Mac app's words. Where the page (ui.html) says the same thing, the string is the page's, word for word:
/// tests/test_macos_parity.py reads this file and the page and fails when they differ. Keep each string on one line.
public enum MacCopy {
    // CONNECT_COPY, the page's words
    public static let connect = "Connect"
    public static let tryAgain = "Try again"
    public static let hangUp = "Hang up"
    public static let cancel = "Cancel"
    public static let notConnected = "Not connected"
    public static let elsewhere = "On a call elsewhere"
    public static let does = "Starts the call on this Mac's microphone"
    public static let noMic = "No microphone found. Plug one in, then press Connect."
    public static let busy = "A call is already up on another page or phone. Hang up there first."
    public static let elsewhereWhy = "The call is on the phone or another page. Hang up there to talk here."
    public static let idleHangup = "The Mac hung up after 30 minutes of quiet. Press Connect to talk again."
    public static let typeLater = "Or type below once connected"
    public static let pressConnect = "Press Connect to start talking"
    public static let typeToo = "Or type below · Press Space to mute"
    public static func connecting(_ place: String) -> String { "Connecting to \(place)…" }
    public static func micFailed(_ why: String) -> String { "The microphone could not start: \(why)" }
    public static func failed(_ why: String) -> String { "The call did not connect\(why.isEmpty ? "" : ": " + why)." }

    // the state line, the page's titles
    public static let notAnswering = "Pointe is not answering"
    public static let reconnecting = "Reconnecting…"
    public static let cannotHear = "Cannot hear you"
    public static let muted = "Muted"
    public static let speaking = "Speaking"
    public static let hearingYou = "Hearing you"
    public static let listening = "Listening"
    public static let challenging = "Challenging"

    // a session's tag in the list, the page's
    public static let tagOffline = "offline"
    public static let tagApprove = "approve"
    public static let tagNeedsYou = "needs you"
    public static let tagWorking = "working"
    public static let tagIdle = "idle"

    // a request's card, the page's buttons
    public static let approve = "Approve"
    public static let deny = "Deny"

    // the Mac app's own lines
    public static let appName = "Pointe"
    public static let micDenied = "Pointe needs the microphone: allow it in System Settings → Privacy & Security → Microphone, then press Connect."
    public static let noEchoCancelling = "This audio device gave no echo cancellation, so the bot may hear itself: use headphones."
    public static let daemonDown = "Pointe on this Mac is not running. Start it here, or run pointe open in a terminal."
    public static let keyRefused = "Pointe on this Mac refused this app. Restart Pointe: Settings → Pointe on this Mac → Restart."
    public static let squatter = "Another program is answering on Pointe's port, so this app sent it nothing."
    public static let node = "This Mac is a node: the call is on its hub. Open Pointe there, or use the phone app."
    public static let noPlugin = "Pointe is not installed on this Mac yet."
    public static let installCommand = "claude plugin marketplace add https://github.com/ballerine-io/pointe.git && claude plugin install pointe@pointe"
    public static let approveReason = "approve a session's request"
    public static let lowerLockReason = "lower the voice lock"
    public static let startReason = "start a new session"
    public static let alreadyAnswered = "Already answered"
    public static let approveOnPage = "Approve this one in the window"
    public static let offlineCard = "offline: answer it in its terminal"
    public static let noSessions = "No sessions yet"
    public static let noSessionsHow = "Run /pointe:voice in a Claude Code session to join it to the voice."
    public static let nothingSaid = "Nothing said yet"
    public static let typeHere = "Type to Pointe"
    public static let openPage = "Open the page"
    public static let thisMac = "This Mac"
    public static func needYou(_ n: Int) -> String { n == 1 ? "1 session needs you" : "\(n) sessions need you" }
    public static func unreachable(_ place: String) -> String { "Pointe on this Mac is not answering at \(place)." }
    public static func versions(daemon: String, app: String) -> String { "Pointe on this Mac is \(daemon); this app is \(app)." }
    public static let updatePlugin = "Update Pointe: pointe update in a terminal (for the Claude Code plugin: claude plugin marketplace update pointe, then claude plugin update pointe@pointe), then Restart."
    public static let updateApp = "Update this app from the release page on GitHub."
}

/// The app's version against the daemon's (the plugin's): they are released together, so a difference says which side
/// is behind.
public enum VersionCheck {
    public enum Verdict: Equatable, Sendable { case same, daemonOlder, appOlder, unknown }

    static func parts(_ version: String) -> [Int]? {
        let fields = version.split(separator: ".").map { Int($0) }
        return fields.isEmpty || fields.contains(nil) ? nil : fields.compactMap { $0 }
    }

    public static func compare(app: String, daemon: String?) -> Verdict {
        guard let daemon, let a = parts(app), let d = parts(daemon) else { return .unknown }
        for i in 0..<max(a.count, d.count) {
            let (x, y) = (i < a.count ? a[i] : 0, i < d.count ? d[i] : 0)
            if x != y { return x > y ? .daemonOlder : .appOlder }
        }
        return .same
    }

    /// What to say and do about it; nil when they agree or the daemon is a development checkout ("dev").
    public static func note(app: String, daemon: String?) -> (line: String, fix: String)? {
        switch compare(app: app, daemon: daemon) {
        case .same, .unknown: nil
        case .daemonOlder: (MacCopy.versions(daemon: daemon ?? "", app: app), MacCopy.updatePlugin)
        case .appOlder: (MacCopy.versions(daemon: daemon ?? "", app: app), MacCopy.updateApp)
        }
    }
}
