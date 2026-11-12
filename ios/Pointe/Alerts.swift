import BackgroundTasks
import SwiftUI
import UIKit
import UserNotifications

// Wrist approvals and alerts (docs/plans/next-features.md, "7."). Pointe has no push server: these are local
// notifications the app posts from its own status polls. iOS mirrors them to an Apple Watch on the wrist while the
// iPhone is locked, and hands an action on the watch back to this app.
//
// When it works: while the app is alive, that is open, or in the background with the call up (background audio keeps
// it running). With the call down and the app in the background, iOS suspends it; it then checks only when iOS grants a
// Background App Refresh, at times iOS picks (often hours apart, never in Low Power Mode, never after the app was swiped
// away). A request answered elsewhere while the app is suspended stays on the lock screen until the next check; an
// action on it gets "Already answered".

enum AlertCopy {
    static let section = "Alerts"
    static let phone = "Alerts on this iPhone"
    static let watchApprove = "Approve from notifications (iPhone and Apple Watch)"
    static let help = "A notification shows what Pointe would read out, never the hidden full text. Its Approve needs an "
        + "unlocked iPhone or a watch on your wrist instead of Face ID, and only for a request Pointe can read out; anything "
        + "else opens the app. Phone alerts need the call to be up or the app open."
    static let suspended = "With the call down and Pointe in the background, iOS lets it check only now and then, at times "
        + "iOS picks, and not at all after you swipe it away."
    static let blocked = "Notifications are off for Pointe. Turn them on in the Settings app."
    static let faceIDReason = "Approve from notifications without Face ID"
    static let alreadyAnswered = "Already answered"
    static let approveInApp = "Approve it in the app"
    static let unreachable = "Mac not reachable. It is still waiting on the Mac and in the app."
}

struct AlertNote: Equatable, Sendable {
    let id: String
    let title: String
    let body: String
    let category: String
    let kind: String
    let session: String?
    let requestId: String?
}

/// Which notifications a status poll posts and withdraws. Pure, so it is tested without iOS.
enum AlertPlan {
    static let approveCategory = "pointe.approve"  // Deny and Approve: a request Pointe can read out, with the setting on
    static let denyCategory = "pointe.deny"        // Deny only: approving needs the app (Face ID) or the page
    static let openCategory = "pointe.open"        // no actions: a tap opens the app

    struct Result: Equatable {
        var post: [AlertNote]
        var withdraw: [String]
        var posted: Set<String>
    }

    /// The Mac's own title and body, never the request's full text: an older Mac sends neither, and gets no notification.
    static func note(_ a: API.Attention, watchApprove: Bool) -> AlertNote? {
        guard let title = a.title, !title.isEmpty, let body = a.body, !body.isEmpty else { return nil }
        let kind = a.kind ?? ""
        guard kind == "permission" else {
            return AlertNote(id: a.id, title: title, body: body, category: openCategory, kind: kind, session: a.session, requestId: nil)
        }
        guard let session = a.session, let requestId = a.request_id else { return nil }
        return AlertNote(id: a.id, title: title, body: body,
                         category: watchApprove && a.approvable == true ? approveCategory : denyCategory,
                         kind: kind, session: session, requestId: requestId)
    }

    /// `posted`: what this app already posted (once each, even if the user swiped it away); `delivered`: what is on
    /// screen now. On screen, the card is enough: an item is posted once the app leaves the screen.
    static func plan(_ items: [API.Attention], posted: Set<String>, delivered: Set<String>, appActive: Bool, enabled: Bool,
                     watchApprove: Bool) -> Result {
        let shown = delivered.union(posted)
        guard enabled else { return Result(post: [], withdraw: shown.sorted(), posted: []) }
        let ids = Set(items.map(\.id))
        var kept = posted.intersection(ids)
        var post: [AlertNote] = []
        if !appActive {
            for a in items where !kept.contains(a.id) {
                guard let n = note(a, watchApprove: watchApprove) else { continue }
                post.append(n)
                kept.insert(a.id)
            }
        }
        return Result(post: post, withdraw: shown.subtracting(ids).sorted(), posted: kept)
    }
}

/// An action on a notification: bound to the session and request it was posted for.
enum AlertAnswer {
    static let approve = "pointe.approve.action"
    static let deny = "pointe.deny.action"

    struct Decision: Equatable, Sendable {
        let session: String
        let requestId: String
        let allow: Bool
    }

    static func decision(action: String, userInfo: [AnyHashable: Any]) -> Decision? {
        guard action == approve || action == deny, let session = userInfo["session"] as? String,
              let requestId = userInfo["request_id"] as? String else { return nil }
        return Decision(session: session, requestId: requestId, allow: action == approve)
    }

    /// What to tell the user afterwards; nil when the answer reached the session.
    static func outcome(_ error: Error?) -> String? {
        guard let error else { return nil }
        if case API.Failure.status(let code, _) = error {
            if code == 409 { return AlertCopy.alreadyAnswered }
            if code == 403 { return AlertCopy.approveInApp }
        }
        return AlertCopy.unreachable
    }
}

extension API {
    /// Its own pinned session, for when no call (and no CallView) is around: an action or a background check.
    static func standalone(_ pairing: Pairing) -> API {
        API(pairing: pairing, session: URLSession(configuration: .ephemeral,
                                                   delegate: PinnedDelegate(fingerprint: pairing.fingerprint), delegateQueue: nil))
    }
}

@MainActor
final class AlertCenter: NSObject, UNUserNotificationCenterDelegate {
    static let shared = AlertCenter()
    nonisolated static let refreshTask = "io.ballerine.pointe.alerts"
    private static let resultPrefix = "result:"

    private let center = UNUserNotificationCenter.current()
    private let defaults = UserDefaults.standard

    var enabled: Bool { defaults.bool(forKey: "pointe.alerts") }

    private var posted: Set<String> {
        get { Set(defaults.stringArray(forKey: "pointe.alerts.posted") ?? []) }
        set { defaults.set(newValue.sorted(), forKey: "pointe.alerts.posted") }
    }

    /// At launch, before an action that launched the app is delivered.
    func start() {
        center.delegate = self
        // Deny first: it is the safe one if a gesture picks the first action.
        let deny = UNNotificationAction(identifier: AlertAnswer.deny, title: "Deny", options: [.destructive])
        let approve = UNNotificationAction(identifier: AlertAnswer.approve, title: "Approve", options: [.authenticationRequired])
        center.setNotificationCategories([
            UNNotificationCategory(identifier: AlertPlan.approveCategory, actions: [deny, approve], intentIdentifiers: []),
            UNNotificationCategory(identifier: AlertPlan.denyCategory, actions: [deny], intentIdentifiers: []),
            UNNotificationCategory(identifier: AlertPlan.openCategory, actions: [], intentIdentifiers: []),
        ])
    }

    /// Turning it on asks iOS (its prompt, once); the result is whether alerts are on now.
    func setEnabled(_ on: Bool) async -> Bool {
        let granted = on ? ((try? await center.requestAuthorization(options: [.alert, .sound])) ?? false) : false
        defaults.set(granted, forKey: "pointe.alerts")
        if !granted { await sync([], api: nil) }
        return granted
    }

    /// After each status poll. A failed poll (nil) changes nothing: it is not "everything was answered".
    func sync(_ attention: [API.Attention]?, api: API?) async {
        guard let attention else { return }
        let delivered = Set(await center.deliveredNotifications().map(\.request.identifier).filter { !$0.hasPrefix(Self.resultPrefix) })
        let active = UIApplication.shared.applicationState == .active
        var watchApprove = false
        let fresh = attention.contains { $0.kind == "permission" && !posted.contains($0.id) }
        if enabled, !active, fresh, let api {  // read the Mac's setting as the notification is built; unknown is off
            watchApprove = (try? await api.prefs())?.watchApprove ?? false
        }
        let r = AlertPlan.plan(attention, posted: posted, delivered: delivered, appActive: active, enabled: enabled,
                               watchApprove: watchApprove)
        if !r.withdraw.isEmpty {
            center.removeDeliveredNotifications(withIdentifiers: r.withdraw)
            center.removePendingNotificationRequests(withIdentifiers: r.withdraw)
        }
        for n in r.post { try? await center.add(Self.request(n)) }
        posted = r.posted
    }

    private static func request(_ n: AlertNote) -> UNNotificationRequest {
        let c = UNMutableNotificationContent()
        c.title = n.title
        c.body = n.body
        c.categoryIdentifier = n.category
        c.threadIdentifier = n.session ?? "pointe"
        c.sound = .default
        // Breaks through a Focus only with the Time Sensitive entitlement; without it iOS delivers it as active.
        c.interruptionLevel = n.kind == "permission" ? .timeSensitive : .active
        var info = ["kind": n.kind]
        if let session = n.session { info["session"] = session }
        if let requestId = n.requestId { info["request_id"] = requestId }
        c.userInfo = info
        return UNNotificationRequest(identifier: n.id, content: c, trigger: nil)
    }

    // MARK: Background App Refresh

    nonisolated static func schedule() {
        let r = BGAppRefreshTaskRequest(identifier: refreshTask)
        r.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
        try? BGTaskScheduler.shared.submit(r)
    }

    /// iOS woke the app: one status check, and the next wake is asked for.
    func refresh() async {
        Self.schedule()
        guard enabled, let pairing = PairingStore.load() else { return }
        let api = API.standalone(pairing)
        await sync((try? await api.status())?.attention, api: api)
    }

    // MARK: actions

    // The completion-handler forms: UIKit requires the handler on the main thread, which the async forms do not keep.
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                            withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .list, .sound])
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                            withCompletionHandler completionHandler: @escaping () -> Void) {
        let content = response.notification.request.content
        let decision = AlertAnswer.decision(action: response.actionIdentifier, userInfo: content.userInfo)
        let id = response.notification.request.identifier, title = content.title
        nonisolated(unsafe) let done = completionHandler
        Task { @MainActor in
            if let decision { await self.answer(decision, id: id, title: title) }
            done()
        }
    }

    private func answer(_ d: AlertAnswer.Decision, id: String, title: String) async {
        guard let pairing = PairingStore.load() else { return }
        var failure: Error?
        do {
            try await API.standalone(pairing).answerFromNotification(session: d.session, requestId: d.requestId, allow: d.allow)
        } catch {
            failure = error
        }
        guard let message = AlertAnswer.outcome(failure) else { return }
        if message == AlertCopy.unreachable { posted.remove(id) }  // still pending: post it again on the next check
        let c = UNMutableNotificationContent()
        c.title = title
        c.body = message
        c.categoryIdentifier = AlertPlan.openCategory
        try? await center.add(UNNotificationRequest(identifier: Self.resultPrefix + id, content: c, trigger: nil))
    }
}

/// Menu → Alerts. The iPhone switch is this phone's; "Approve from notifications" is the Mac's, shared with the page.
struct AlertsSheet: View {
    @State private var phone: Bool
    @State private var watch: Bool
    @State private var note: String?
    private let setPhone: (Bool) async -> Bool
    private let setWatch: (Bool) async -> Bool

    init(phone: Bool, watch: Bool, setPhone: @escaping (Bool) async -> Bool, setWatch: @escaping (Bool) async -> Bool) {
        _phone = State(initialValue: phone)
        _watch = State(initialValue: watch)
        self.setPhone = setPhone
        self.setWatch = setWatch
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Toggle(AlertCopy.phone, isOn: Binding(get: { phone }, set: { on in
                        phone = on
                        Task { phone = await setPhone(on); note = on && !phone ? AlertCopy.blocked : nil }
                    }))
                    .accessibilityIdentifier("alertsPhone")
                    Toggle(AlertCopy.watchApprove, isOn: Binding(get: { watch }, set: { on in
                        Task { watch = await setWatch(on) }  // moves only once Face ID and the Mac agree
                    }))
                    .accessibilityIdentifier("alertsWatchApprove")
                } footer: {
                    Text(AlertCopy.help).accessibilityIdentifier("alertsHelp")
                }
                Section {
                    Text(AlertCopy.suspended).font(.footnote).foregroundStyle(.secondary)
                }
                if let note {
                    Text(note).foregroundStyle(Brand.orange).accessibilityIdentifier("alertsNote")
                }
            }
            .navigationTitle(AlertCopy.section)
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}
