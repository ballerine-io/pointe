import Foundation

/// Starting a new session from Pointe (docs/design/new-session.md): the sheet, the rows and the read-back card say the
/// same words on the page (`NEW_SESSION_COPY` in ui.html), the iPhone app (apps/PointeKit/Sources/PointeUI/NewSession.swift) and the Mac app.
/// The parity tests read this file: keep each string on one line.
public enum NewSessionCopy {
    public static let title = "New session"
    public static let lede = "Starts a coding agent in a folder you already work in. It joins the voice by itself. Whether Claude Code asks before it acts is a setting: Permissions for new sessions."
    public static let agent = "Agent"
    public static let machine = "Machine"
    public static let folder = "Folder"
    public static let name = "Name"
    public static let namePlaceholder = "Same as the folder"
    public static let prompt = "First prompt"
    public static let promptPlaceholder = "Optional. Sent once the session has joined."
    public static let start = "Start"
    public static let cancel = "Cancel"
    public static let noFolders = "No folder yet. A session must join from a folder first, or add one in Settings on the Mac."
    public static let claudeNote = "Claude Code opens in a new terminal window on the Mac."
    public static let starting = "starting"
    public static let failed = "did not start"
    public static let confirmTitle = "Start this session?"
    public static let foldersTitle = "New sessions"
    public static let foldersHelp = "Folders a new session may start in, beside the folders of your current and recent sessions. Changed on the Mac only."
    // Permissions for new sessions (prefs "sessions.permissions"; newsession.PERMISSIONS on the Mac): the Settings row.
    public static let permissionsSetting = "Permissions for new sessions"
    public static let permissionsSkip = "Skip permission prompts"
    public static let permissionsAsk = "Ask before actions"
    public static let permissionsHint = "Skip permission prompts: a new Claude Code session Pointe starts can edit files and run commands without asking, so there are no requests to approve. Ask before actions: it asks first, and you answer by voice or a tap. Say “start a session that asks first” for one session."
    /// Under a starting row the first time a start skips prompts, as the Mac says it (newsession.SKIP_NOTICE).
    public static let skipNotice = "New sessions skip permission prompts: they can edit files and run commands without asking. Say “ask first”, or change it in Settings."
}
