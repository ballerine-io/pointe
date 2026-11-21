import Foundation

// The words the page, the iPhone app and the Mac app share. Each dictionary is held to ui.html's by the parity tests
// (tests/test_copy_parity.py, test_turn_taking.py, test_brain_dump.py, test_ptt_modes.py, test_macos_parity.py):
// keep each string on one line, in the form `static let name = "…"`.

/// Connect: the one control that starts the call. Its words are the page's (`CONNECT_COPY` in ui.html); the parity
/// tests on both sides hold them to the same text.
public enum ConnectCopy {
    public static let connect = "Connect"
    public static let tryAgain = "Try again"
    public static let hangUp = "Hang up"
    public static let cancel = "Cancel"
    public static let connectFirst = "Connect first"
    public static let notConnected = "Not connected"
    public static let notPairedTitle = "Not paired"
    public static let unreachableTitle = "Mac not reachable"
    public static let elsewhere = "On a call elsewhere"
    public static let does = "Starts the call on this iPhone's microphone"
    public static let tapConnect = "Tap Connect to start talking"
    public static let redialling = "The call dropped. It comes back by itself; Cancel stops the redials."
    public static let elsewhereWhy = "The call is on the Mac's page or another phone. Hang up there to talk here."
    public static let busy = "A call is already up on another page or phone. Hang up there first."
    public static let notPaired = "This phone is no longer paired. Pair again from the page: Settings → Phone → Connect your phone."
    public static let idleHangup = "The Mac hung up after 30 minutes of quiet. Tap Connect to talk again."
    public static let micDenied = "Pointe needs the microphone: allow it in Settings, then tap Connect."
    /// Under Connect: the type bar opens from the keyboard button, and typing needs the call (the page's typeLaterTap).
    public static let typeLaterTap = "Once connected, tap the keyboard to type"
    public static func connecting(_ place: String) -> String { "Connecting to \(place)…" }
    public static func micFailed(_ why: String) -> String { "The microphone could not start: \(why)" }
    public static func failed(_ why: String) -> String { "The call did not connect\(why.isEmpty ? "" : ": " + why)." }
    /// From the phone, a Mac that does not answer and a Mac whose phone listener is off look the same: say both.
    public static func unreachable(_ host: String) -> String {
        "Can't reach your Mac at \(host). Is Twingate or Tailscale on? Is the Mac awake?"
            + " If so, its phone listener may be off: on the Mac, Settings → Phone → Connect your phone."
    }

    public static func offTitle(reach: Reach, macOnACall: Bool) -> String {
        switch reach {
        case .rejected: return notPairedTitle
        case .unreachable: return unreachableTitle
        case .ok: return macOnACall ? elsewhere : notConnected
        }
    }
}

/// Turn taking (docs/design/turn-taking.md): how long a pause ends a sentence, and a hold ("don't interrupt me") that
/// keeps the Mac quiet until "go ahead" or 8 s of quiet. The Mac's pref "turns.patience" is the truth, set here or on
/// the page; the words are the page's, word for word (tests/test_turn_taking.py checks both).
/// Whether /voice/status answers: the Mac away, or the Mac refusing this client's key, are two different problems.
public enum Reach: Equatable, Sendable { case ok, unreachable, rejected }

public enum TurnsCopy {
    public static let setting = "Wait before answering"
    public static let levels: [(value: String, label: String)] = [("quick", "Quick"), ("normal", "Normal"), ("patient", "Patient")]
    public static let holding = "Holding"
    public static let holdingHow = "Say “go ahead” when you're done"  // the line under the state
    public static let failed = "The Mac did not take the setting. Is Pointe on the Mac up to date?"
    public static let defaultLevel = "normal"
}

/// Settings → About: the same words as the page's ABOUT_COPY (tests/test_copy_parity.py).
public enum AboutCopy {
    public static let title = "About"
    public static let body = "Pointe is open source (MIT). Built and open-sourced by Ballerine Engineering."
    public static let repo = "Source code on GitHub"
    public static let repoURL = "https://github.com/ballerine-io/pointe"
    public static let maker = "ballerine.com"
    public static let makerURL = "https://ballerine.com"
    public static let version = "Version"
}

