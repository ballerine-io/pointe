#if os(iOS)
import BackgroundTasks
#endif
import SwiftUI
#if canImport(UIKit)
import UIKit
#endif
import UserNotifications

// Wrist approvals and alerts (docs/features/alerts.md). Pointe has no push server: these are local
// notifications the app posts from its own status polls. iOS mirrors them to an Apple Watch on the wrist while the
// iPhone is locked, and hands an action on the watch back to this app.
//
// When it works: while the app is alive, that is open, or in the background with the call up (background audio keeps
// it running). With the call down and the app in the background, iOS suspends it; it then checks only when iOS grants a
// Background App Refresh, at times iOS picks (often hours apart, never in Low Power Mode, never after the app was swiped
// away). A request answered elsewhere while the app is suspended stays on the lock screen until the next check; an
// action on it gets "Already answered".

/// The Alerts sheet's lines as the Mac app says them: this Mac, Touch ID, System Settings.
extension AlertCopy {
    static var phoneHere: String { Surface.isMac ? "Alerts on this Mac" : phone }
    static var helpHere: String {
        Surface.isMac ? "A notification shows what Pointe would read out, never the hidden full text. Its Approve is offered only for a "
            + "request Pointe can read out, and a locked Mac asks to unlock first; anything else opens the window, where Approve asks "
            + "for Touch ID or your password. The second setting is shared with the page and the phone." : help
    }
    static var blockedHere: String { Surface.isMac ? "Notifications are off for Pointe. Turn them on in System Settings → Notifications." : blocked }
    static var faceIDReasonHere: String { Surface.isMac ? "Approve from notifications without Touch ID" : faceIDReason }
}

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

    /// The Mac's title, naming the machine when the session runs on somebody else's and the title does not say so yet:
    /// "shop needs approval" becomes "shop on avi-box needs approval".
    static func title(_ title: String, for s: API.Session, machines: MachineView) -> String {
        let machine = machines.of(s)
        guard machine != machines.here, !machine.isEmpty, machines.ownerTag(machine: machine) != nil || !s.isMine,
              !title.contains(machine) else { return title }
        return title.hasPrefix(s.name) ? machines.label(s) + title.dropFirst(s.name.count) : "\(title), on \(machine)"
    }
}

struct AlertNote: Equatable, Sendable {
    let id: String
    let title: String
    let body: String
    let category: String
    let kind: String
    let session: String?
    let requestId: String?
    /// With several machines: the pairing an action on it goes to (AlertMerge).
    var machine: String? = nil
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
    /// The Mac names the machine in the title (alerts.py). A session whose machine is offline gets no actions: an answer
    /// would be stale, its prompt went back to its terminal.
    /// A session on somebody else's machine says which machine ("shop on avi-box needs approval"), and one this person
    /// may only watch raises no approval: its prompt is its owner's to answer.
    static func note(_ a: API.Attention, watchApprove: Bool, machines: MachineView = MachineView(nil)) -> AlertNote? {
        noteAt(a, watchApprove: watchApprove, machines: machines).map { var n = $0; n.machine = a.via; return n }
    }

    private static func noteAt(_ a: API.Attention, watchApprove: Bool, machines: MachineView) -> AlertNote? {
        guard let said = a.title, !said.isEmpty, let body = a.body, !body.isEmpty else { return nil }
        let s = a.session.flatMap { name in machines.sessions.first { $0.name == name } }
        if let s, machines.watchOnly(s), a.kind == "permission" { return nil }
        // Somebody else is asked first: nothing here until the prompt opens to this person.
        if let s, machines.waitsFor(s) != nil, a.kind == "permission" { return nil }
        let title = s.map { AlertCopy.title(said, for: $0, machines: machines) } ?? said
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
    static func key(_ n: AlertNote) -> String { "\(n.id)|\(n.category)" }

    /// The notification id of a `posted` entry (one stored by an older build is a bare id).
    static func id(ofKey key: String) -> String {
        guard let bar = key.lastIndex(of: "|") else { return key }
        return String(key[..<bar])
    }

    /// Posted for this id with its actions, or for anything but a permission: no Mac setting needs reading again.
    static func postedWithActions(_ id: String, in posted: Set<String>) -> Bool {
        posted.contains { Self.id(ofKey: $0) == id && !$0.hasSuffix("|" + openCategory) }
    }

    /// `posted`: what this app already posted (once each per category, even if the user swiped it away); `delivered`:
    /// what is on screen now. On screen, the card is enough: an item is posted once the app leaves the screen.
    /// With several machines (`current` set): an item from another machine is judged without the current one's
    /// sessions (a session of the same name there is another session), and may be approved from a notification only as
    /// that machine's own setting says (`watchApproveBy`, unknown is off).
    static func plan(_ items: [API.Attention], posted: Set<String>, delivered: Set<String>, appActive: Bool, enabled: Bool,
                     watchApprove: Bool, machines: MachineView = MachineView(nil), current: String? = nil,
                     watchApproveBy: [String: Bool] = [:]) -> Result {
        let shown = delivered.union(posted.map { id(ofKey: $0) })
        guard enabled else { return Result(post: [], withdraw: shown.sorted(), posted: []) }
        let ids = Set(items.map(\.id))
        var kept = posted.filter { ids.contains(id(ofKey: $0)) }
        var post: [AlertNote] = []
        if !appActive {
            // A quiet item is not recorded as posted: it is posted on the first poll after the user leaves the Mac.
            for a in items where a.quiet != true {
                let elsewhere = current != nil && a.via != nil && a.via != current
                guard let n = note(a, watchApprove: elsewhere ? watchApproveBy[a.via ?? ""] ?? false : watchApprove,
                                   machines: elsewhere ? MachineView(nil) : machines) else { continue }
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
enum AlertAnswer {
    static let approve = "pointe.approve.action"
    static let deny = "pointe.deny.action"

    struct Decision: Equatable, Sendable {
        let session: String
        let requestId: String
        let allow: Bool
        var machine: String? = nil
    }

    static func decision(action: String, userInfo: [AnyHashable: Any]) -> Decision? {
        guard action == approve || action == deny, let session = userInfo["session"] as? String,
              let requestId = userInfo["request_id"] as? String else { return nil }
        return Decision(session: session, requestId: requestId, allow: action == approve, machine: userInfo["machine"] as? String)
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
    /// Its own session, for when no call (and no CallView) is around: an action or a background check.
    static func standalone(_ link: DaemonLink) -> API {
        API(link: link, session: link.session(onOpen: {}))
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

    /// The Mac app's link to its daemon, and whether its window is the one in front: set by the app. The iPhone has its
    /// pairing in the Keychain and asks iOS whether it is on screen.
    var local: DaemonLink?
    var isFront: @MainActor () -> Bool = { true }
    /// A notification was clicked (the Mac brings its window forward; iOS opens the app by itself).
    var opened: @MainActor () -> Void = {}

    private var link: DaemonLink? {
        #if os(iOS)
        PairingStore.load().map(DaemonLink.init)
        #else
        local
        #endif
    }

    /// Each machine's last attention, by pairing (one entry, "here", on the Mac app and with several machines off).
    private var latest: [String: AlertMerge.Source] = [:]
    /// Each other machine's "Approve from notifications", read when a fresh request of its own arrives.
    private var watchApproveBy: [String: Bool] = [:]

    private var several: Bool {
        #if os(iOS)
        SeveralMachines.on
        #else
        false
        #endif
    }

    /// The link an action goes to: the pairing it was posted for, else the current machine.
    private func link(for machine: String?) -> DaemonLink? {
        #if os(iOS)
        if let machine, let p = PairingStore.all().first(where: { $0.storeKey == machine }) { return DaemonLink(p) }
        #endif
        return link
    }

    private var appActive: Bool {
        #if os(iOS)
        UIApplication.shared.applicationState == .active
        #else
        isFront()
        #endif
    }

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

    /// After each status poll. A failed poll (nil) changes nothing: it is not "everything was answered". `from`: the
    /// machine it came from, when it is not the current one (several machines); its alerts join the current one's.
    func sync(_ attention: [API.Attention]?, api: API?, machines: MachineView = MachineView(nil), from: Pairing? = nil) async {
        guard let incoming = attention else { return }
        var current: String? = nil
        let attention: [API.Attention]
        if several {
            let all = PairingStore.all()
            let source = from ?? PairingStore.load()
            current = PairingStore.load()?.storeKey
            if let source {
                let id = source.id ?? machines.machines.first(where: \.isHere)?.machine_id
                latest[source.storeKey] = AlertMerge.Source(key: source.storeKey, name: source.label, machineId: id, items: incoming)
            }
            latest = latest.filter { key, _ in all.contains { $0.storeKey == key } }  // a machine removed posts nothing more
            let ordered = all.compactMap { latest[$0.storeKey] }
            attention = AlertMerge.merge(ordered)
            if let from, from.storeKey != current, enabled, !appActive,
               incoming.contains(where: { $0.kind == "permission" }), watchApproveBy[from.storeKey] == nil {
                watchApproveBy[from.storeKey] = (try? await API.standalone(DaemonLink(from)).prefs())?.watchApprove ?? false
            }
        } else {
            attention = incoming
        }
        let delivered = Set(await center.deliveredNotifications().map(\.request.identifier).filter { !$0.hasPrefix(Self.resultPrefix) })
        let active = appActive
        var watchApprove = false
        let fresh = attention.contains { $0.kind == "permission" && !AlertPlan.postedWithActions($0.id, in: posted) }
        if enabled, !active, fresh, let api {  // read the Mac's setting as the notification is built; unknown is off
            watchApprove = (try? await api.prefs())?.watchApprove ?? false
        }
        let r = AlertPlan.plan(attention, posted: posted, delivered: delivered, appActive: active, enabled: enabled,
                               watchApprove: watchApprove, machines: machines, current: current, watchApproveBy: watchApproveBy)
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
        if let machine = n.machine { info["machine"] = machine }
        c.userInfo = info
        return UNNotificationRequest(identifier: n.id, content: c, trigger: nil)
    }

    // MARK: Background App Refresh

    /// The Mac app is never suspended: its menu bar item keeps the check running, and there is nothing to schedule.
    nonisolated static func schedule() {
        #if os(iOS)
        let r = BGAppRefreshTaskRequest(identifier: refreshTask)
        r.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
        try? BGTaskScheduler.shared.submit(r)
        #endif
    }

    /// iOS woke the app: one status check, and the next wake is asked for.
    func refresh() async {
        Self.schedule()
        guard enabled, let link else { return }
        let api = API.standalone(link)
        let status = try? await api.status()
        await sync(status?.attention, api: api, machines: MachineView(status))
        #if os(iOS)
        guard several else { return }
        let current = PairingStore.load()?.storeKey
        for p in PairingStore.all() where p.storeKey != current {  // each other machine once; one that does not answer changes nothing
            let other = try? await API.standalone(DaemonLink(p)).status()
            await sync(other?.attention, api: nil, machines: MachineView(other), from: p)
        }
        #endif
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
        let clicked = response.actionIdentifier == UNNotificationDefaultActionIdentifier
        let reply = AlertOpen.agentReply(action: response.actionIdentifier, userInfo: content.userInfo)
        Task { @MainActor in
            if let decision { await self.answer(decision, id: id, title: title) }
            if clicked { self.opened() }
            if let reply { AgentReplyOpener.shared.agent = AgentName(id: reply) }
            done()
        }
    }

    private func answer(_ d: AlertAnswer.Decision, id: String, title: String) async {
        guard let link = link(for: d.machine) else { return }
        var failure: Error?
        do {
            try await API.standalone(link).answerFromNotification(session: d.session, requestId: d.requestId, allow: d.allow)
        } catch {
            failure = error
        }
        guard let message = AlertAnswer.outcome(failure) else { return }
        if message == AlertCopy.unreachable { posted = posted.filter { AlertPlan.id(ofKey: $0) != id } }  // still pending: post it again on the next check
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
    @Environment(\.dismiss) private var dismiss

    init(phone: Bool, watch: Bool, setPhone: @escaping (Bool) async -> Bool, setWatch: @escaping (Bool) async -> Bool) {
        _phone = State(initialValue: phone)
        _watch = State(initialValue: watch)
        self.setPhone = setPhone
        self.setWatch = setWatch
    }

    var body: some View {
        NavigationStack {
            BrandForm {
                Section {
                    Toggle(AlertCopy.phoneHere, isOn: Binding(get: { phone }, set: { on in
                        phone = on
                        Task { phone = await setPhone(on); note = on && !phone ? AlertCopy.blockedHere : nil }
                    }))
                    .accessibilityIdentifier("alertsPhone")
                    Toggle(AlertCopy.watchApprove, isOn: Binding(get: { watch }, set: { on in
                        Task { watch = await setWatch(on) }  // moves only once Face ID and the Mac agree
                    }))
                    .accessibilityIdentifier("alertsWatchApprove")
                } footer: {
                    Group {
                        Text(AlertCopy.helpHere).accessibilityIdentifier("alertsHelp")
                    }.brandFootnote()
                }
                #if os(iOS)  // the Mac app is never suspended: its menu bar item keeps checking
                Section {
                    Text(AlertCopy.suspended).font(.brand(.footnote)).foregroundStyle(Brand.muted)
                }
                #endif
                if let note {
                    Text(note).foregroundStyle(Brand.accent).accessibilityIdentifier("alertsNote")
                }
            }
            .sheetTitle(AlertCopy.section)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}
