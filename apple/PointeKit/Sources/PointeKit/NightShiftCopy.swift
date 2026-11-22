import Foundation

/// The night shift (docs/design/night-shift.md): the start sheet, the strip, the read-back card and the ledger say the
/// same words on the page (`NIGHT_SHIFT_COPY` in ui.html), the iPhone app (apple/PointeKit/Sources/PointeUI/NightShift.swift) and the Mac app.
/// The parity tests read this file: keep each string on one line, in the page's order.
public enum NightShiftCopy {
    public static let title = "Night shift"
    public static let lede = "Give your sessions work for while you are away. Pointe keeps them moving, and the morning briefing leads with what was decided and what waits on you."
    public static let rule = "Pointe approves nothing: a session that needs approval waits for you."
    public static let session = "Session"
    public static let task = "Task"
    public static let taskPlaceholder = "What it should get done tonight"
    public static let addTask = "Add a task"
    public static let newSession = "New session"
    public static let hours = "Hours"
    public static let messages = "Messages"
    public static let notify = "Alert me about blockers overnight"
    public static let start = "Start shift"
    public static let cancel = "Cancel"
    public static let stop = "Stop shift"
    public static let confirmTitle = "Start this night shift?"
    public static let ledger = "Ledger"
    public static let decided = "Decisions made without you"
    public static let asked = "Questions waiting on you"
    public static let done = "Done"
    public static let blocked = "Blocked"
    public static let inFlight = "In flight"
    public static let notStarted = "Not started"
    public static let exact = "The exact request"
    public static let empty = "No night shift yet."
    public static let noSessions = "No session is on the voice yet. Join one, then give it a task."
    public static let history = "Last 7 shifts"
    public static let running = "running"
}
