import AppKit
import ServiceManagement

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
