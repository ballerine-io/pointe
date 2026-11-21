import AppKit
import LocalAuthentication
import OSLog
import PointeKit
import ServiceManagement
@preconcurrency import UserNotifications

/// Approve asks who is there: Touch ID, an Apple Watch, or the account password, where the iPhone asks for Face ID.
struct DeviceOwner: Authenticating {
    func confirm(reason: String) async -> Bool {
        let context = LAContext()
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else { return false }
        return (try? await context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason)) ?? false
    }
}

/// The stub's stand-in, for the UI tests: it never shows the system sheet.
struct FixedOwner: Authenticating {
    let answer: Bool
    func confirm(reason: String) async -> Bool { answer }
}

/// Start at login, through `SMAppService`: the user sees and can remove it in System Settings → General → Login Items.
@MainActor
enum LoginItem {
    static var isOn: Bool { SMAppService.mainApp.status == .enabled }

    /// Returns what went wrong, or nil.
    static func set(_ on: Bool) -> String? {
        do {
            if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
            return nil
        } catch {
            return error.localizedDescription
        }
    }
}

/// Local notifications for what needs the person (docs/features/alerts.md): the daemon's own title and body, with Deny
/// and, only where the daemon allows it, Approve. An action is bound to the request it was posted for.
@MainActor
final class Notifier: NSObject, AlertPosting, UNUserNotificationCenterDelegate {
    var answer: ((AlertAnswer.Decision) async -> String?)?
    var open: (() -> Void)?
    private let center = UNUserNotificationCenter.current()
    private let log = Logger(subsystem: Log.subsystem, category: "alerts")

    func install() {
        center.delegate = self
        let deny = UNNotificationAction(identifier: AlertAnswer.deny, title: MacCopy.deny, options: [.destructive])
        // Approve on a locked Mac asks to unlock first.
        let approve = UNNotificationAction(identifier: AlertAnswer.approve, title: MacCopy.approve, options: [.authenticationRequired])
        center.setNotificationCategories([
            UNNotificationCategory(identifier: AlertPlan.approveCategory, actions: [deny, approve], intentIdentifiers: []),
            UNNotificationCategory(identifier: AlertPlan.denyCategory, actions: [deny], intentIdentifiers: []),
            UNNotificationCategory(identifier: AlertPlan.openCategory, actions: [], intentIdentifiers: []),
        ])
    }

    /// Asks once; true when alerts may be shown.
    func authorize() async -> Bool {
        (try? await center.requestAuthorization(options: [.alert, .sound])) ?? false
    }

    func delivered() async -> Set<String> {
        Set(await center.deliveredNotifications().map(\.request.identifier))
    }

    func post(_ notes: [AlertNote]) {
        for note in notes {
            let content = UNMutableNotificationContent()
            content.title = note.title
            content.body = note.body
            content.sound = .default
            content.categoryIdentifier = note.category
            var info: [String: String] = ["kind": note.kind]
            if let session = note.session { info["session"] = session }
            if let id = note.requestId { info["request_id"] = id }
            content.userInfo = info
            center.add(UNNotificationRequest(identifier: note.id, content: content, trigger: nil))
        }
    }

    func withdraw(_ ids: [String]) {
        center.removeDeliveredNotifications(withIdentifiers: ids)
        center.removePendingNotificationRequests(withIdentifiers: ids)
    }

    private func say(_ line: String) {
        let content = UNMutableNotificationContent()
        content.title = MacCopy.appName
        content.body = line
        center.add(UNNotificationRequest(identifier: "pointe.outcome", content: content, trigger: nil))
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        let action = response.actionIdentifier
        let decision = AlertAnswer.decision(action: action, userInfo: response.notification.request.content.userInfo)
        await MainActor.run {
            guard let decision else { self.open?(); return }
            Task { if let line = await self.answer?(decision) { self.say(line) } }
        }
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        [.banner, .sound]
    }
}
