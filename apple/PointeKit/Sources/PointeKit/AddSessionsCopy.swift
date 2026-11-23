import Foundation

/// Adding sessions the user already runs or ran (docs/design/attach-by-voice.md): the sheet and the read-back card say
/// the same words on the page (`ADD_SESSIONS_COPY` in ui.html), the iPhone app and the Mac app.
/// The parity tests read this file: keep each string on one line.
public enum AddSessionsCopy {
    public static let title = "Add sessions"
    public static let lede = "Sessions you run now, and ones you ran this week. Adding one gives the voice its transcript: it reports on it, sends to it and answers its prompts."
    public static let searchPlaceholder = "Search by name, folder or what you asked"
    public static let open = "Open now"
    public static let recent = "This week"
    public static let join = "Join"
    public static let reopen = "Reopen"
    public static let cancel = "Cancel"
    public static let loading = "Looking for sessions…"
    public static let none = "No session to add: every open one is on the voice already."
    public static let noMatch = "No session fits that search."
    public static let approvalsTerminal = "Its approvals stay in its terminal."
    public static let reopenNote = "A Claude Code session reopens in a new terminal window on the Mac."
    public static let confirmTitle = "Add these sessions?"
}
