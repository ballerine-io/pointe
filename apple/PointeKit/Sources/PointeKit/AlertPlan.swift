import Foundation

// Which notifications a status poll posts and withdraws, and what an action on one means (docs/features/alerts.md).
// Pure: each platform posts them with UserNotifications.

public struct AlertNote: Equatable, Sendable {
    public let id: String
    public let title: String
    public let body: String
    public let category: String
    public let kind: String
    public let session: String?
    public let requestId: String?
}

/// Which notifications a status poll posts and withdraws. Pure, so it is tested without iOS.
public enum AlertPlan {
    public static let approveCategory = "pointe.approve"  // Deny and Approve: a request Pointe can read out, with the setting on
    public static let denyCategory = "pointe.deny"        // Deny only: approving needs the app (Face ID) or the page
    public static let openCategory = "pointe.open"        // no actions: a tap opens the app

    public struct Result: Equatable, Sendable {
        var post: [AlertNote]
        var withdraw: [String]
        var posted: Set<String>
    }

    /// The Mac's own title and body, never the request's full text: an older Mac sends neither, and gets no notification.
    /// The Mac names the machine in the title (alerts.py). A session whose machine is offline gets no actions: an answer
    /// would be stale, its prompt went back to its terminal.
    public static func note(_ a: API.Attention, watchApprove: Bool, machines: MachineView = MachineView(nil)) -> AlertNote? {
        guard let title = a.title, !title.isEmpty, let body = a.body, !body.isEmpty else { return nil }
        let s = a.session.flatMap { name in machines.sessions.first { $0.name == name } }
        if s?.isOffline == true {
            return AlertNote(id: a.id, title: title, body: body, category: openCategory, kind: a.kind ?? "", session: a.session, requestId: nil)
        }
        let kind = a.kind ?? ""
        if kind == "briefing" { return nil }  // the phone schedules its own "Your briefing is ready" (BriefingReminder)
        guard kind == "permission" else {
            return AlertNote(id: a.id, title: title, body: body, category: openCategory, kind: kind, session: a.session, requestId: nil)
        }
        guard let session = a.session, let requestId = a.request_id else { return nil }
        return AlertNote(id: a.id, title: title, body: body,
                         category: watchApprove && a.approvable == true ? approveCategory : denyCategory,
                         kind: kind, session: session, requestId: requestId)
    }

    /// What `posted` records for a note: its id and its category. A request posted without actions while its machine was
    /// offline is posted again, with them, once the machine is back (same identifier: it replaces the old one). An entry
    /// stored by an older build is a bare id: it counts as posted with actions, so nothing is posted twice.
    public static func key(_ n: AlertNote) -> String { "\(n.id)|\(n.category)" }

    /// The notification id of a `posted` entry (one stored by an older build is a bare id).
    public static func id(ofKey key: String) -> String {
        guard let bar = key.lastIndex(of: "|") else { return key }
        return String(key[..<bar])
    }

    /// Posted for this id with its actions, or for anything but a permission: no Mac setting needs reading again.
    public static func postedWithActions(_ id: String, in posted: Set<String>) -> Bool {
        posted.contains { Self.id(ofKey: $0) == id && !$0.hasSuffix("|" + openCategory) }
    }

    /// `posted`: what this app already posted (once each per category, even if the user swiped it away); `delivered`:
    /// what is on screen now. On screen, the card is enough: an item is posted once the app leaves the screen.
    public static func plan(_ items: [API.Attention], posted: Set<String>, delivered: Set<String>, appActive: Bool, enabled: Bool,
                     watchApprove: Bool, machines: MachineView = MachineView(nil)) -> Result {
        let shown = delivered.union(posted.map { id(ofKey: $0) })
        guard enabled else { return Result(post: [], withdraw: shown.sorted(), posted: []) }
        let ids = Set(items.map(\.id))
        var kept = posted.filter { ids.contains(id(ofKey: $0)) }
        var post: [AlertNote] = []
        if !appActive {
            // A quiet item is not recorded as posted: it is posted on the first poll after the user leaves the Mac.
            for a in items where a.quiet != true {
                guard let n = note(a, watchApprove: watchApprove, machines: machines) else { continue }
                // Once per id; again only when one posted with no actions (its machine offline) now has them.
                if let before = kept.first(where: { id(ofKey: $0) == n.id }),
                   !(before.hasSuffix("|" + openCategory) && n.category != openCategory) { continue }
                post.append(n)
                kept = kept.filter { id(ofKey: $0) != n.id }
                kept.insert(key(n))
            }
        }
        return Result(post: post, withdraw: shown.subtracting(ids).sorted(), posted: kept)
    }
}

/// An action on a notification: bound to the session and request it was posted for.
public enum AlertAnswer {
    public static let approve = "pointe.approve.action"
    public static let deny = "pointe.deny.action"

    public struct Decision: Equatable, Sendable {
        let session: String
        let requestId: String
        let allow: Bool
    }

    public static func decision(action: String, userInfo: [AnyHashable: Any]) -> Decision? {
        guard action == approve || action == deny, let session = userInfo["session"] as? String,
              let requestId = userInfo["request_id"] as? String else { return nil }
        return Decision(session: session, requestId: requestId, allow: action == approve)
    }

    /// What happened to an answer that did not reach the session; each client says it in its own words.
    public enum Outcome: Equatable, Sendable { case alreadyAnswered, approveInApp, unreachable }

    /// nil when the answer reached the session. 409: no longer pending. 403: this request needs the app or the page.
    public static func outcome(_ error: Error?) -> Outcome? {
        guard let error else { return nil }
        if case API.Failure.status(let code, _) = error {
            if code == 409 { return .alreadyAnswered }
            if code == 403 { return .approveInApp }
        }
        return .unreachable
    }
}

