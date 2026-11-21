// Drives a running app through the Accessibility API, by the identifiers its views carry: for macos/e2e/live.py, which
// runs the real app against a real daemon. XCUITest needs the owner to unlock Automation Mode each session; this needs
// only the Accessibility permission of the terminal that runs it.
//
//   axdrive <pid> press <id>            press the control
//   axdrive <pid> value <id>            print its value, title or label
//   axdrive <pid> label <id>            print its label (what VoiceOver reads), else its title or value
//   axdrive <pid> exists <id>           exit 0 when it is on screen
//   axdrive <pid> labelled <prefix>     print every label that starts with the prefix
//   axdrive <pid> count <id>            how many texts are inside it
//   axdrive <pid> window                print the id of the app's main window (for screencapture -l)
//   axdrive <pid> button <title>        press the first button with this title (a system prompt's "Allow")
import ApplicationServices
import Foundation

let args = CommandLine.arguments
guard args.count >= 3, let pid = pid_t(args[1]) else {
    FileHandle.standardError.write(Data("usage: axdrive <pid> press|value|label|exists|labelled|count|window|button [what]\n".utf8))
    exit(2)
}
guard AXIsProcessTrusted() else {
    FileHandle.standardError.write(Data("axdrive: this terminal has no Accessibility permission (System Settings → Privacy & Security)\n".utf8))
    exit(3)
}
let app = AXUIElementCreateApplication(pid)

func attribute(_ element: AXUIElement, _ name: String) -> AnyObject? {
    var value: AnyObject?
    return AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success ? value : nil
}

func text(_ element: AXUIElement, labelFirst: Bool = false) -> String {
    let order = labelFirst ? [kAXDescriptionAttribute, kAXTitleAttribute, kAXValueAttribute] : [kAXValueAttribute, kAXTitleAttribute, kAXDescriptionAttribute]
    for name in order {
        if let found = attribute(element, name as String) as? String, !found.isEmpty { return found }
    }
    return ""
}

/// Every element under `root`, depth first. An app's tree is a few hundred elements.
func walk(_ root: AXUIElement, _ visit: (AXUIElement) -> Bool, depth: Int = 0) -> Bool {
    if visit(root) { return true }
    guard depth < 40, let children = attribute(root, kAXChildrenAttribute as String) as? [AXUIElement] else { return false }
    for child in children where walk(child, visit, depth: depth + 1) { return true }
    return false
}

func find(_ id: String) -> AXUIElement? {
    var found: AXUIElement?
    _ = walk(app) { element in
        guard attribute(element, kAXIdentifierAttribute as String) as? String == id else { return false }
        found = element
        return true
    }
    return found
}

let what = args.count > 3 ? args[3...].joined(separator: " ") : ""
switch args[2] {
case "press":
    guard let element = find(what) else { print("missing"); exit(1) }
    exit(AXUIElementPerformAction(element, kAXPressAction as CFString) == .success ? 0 : 1)
case "value":
    guard let element = find(what) else { print("missing"); exit(1) }
    print(text(element))
case "label":
    guard let element = find(what) else { print("missing"); exit(1) }
    print(text(element, labelFirst: true))
case "exists":
    exit(find(what) == nil ? 1 : 0)
case "labelled":
    _ = walk(app) { element in
        let label = attribute(element, kAXDescriptionAttribute as String) as? String ?? ""
        if label.hasPrefix(what) { print(label) }
        return false
    }
case "count":
    guard let element = find(what) else { print(0); exit(1) }
    var n = 0
    _ = walk(element) { inner in
        if attribute(inner, kAXRoleAttribute as String) as? String == kAXStaticTextRole as String { n += 1 }
        return false
    }
    print(n)
case "window":
    let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
    let mine = windows.filter { ($0[kCGWindowOwnerPID as String] as? pid_t) == pid && ($0[kCGWindowLayer as String] as? Int) == 0 }
    guard let id = mine.first?[kCGWindowNumber as String] as? Int else { exit(1) }
    print(id)
case "button":
    var pressed = false
    _ = walk(app) { element in
        guard attribute(element, kAXRoleAttribute as String) as? String == kAXButtonRole as String,
              attribute(element, kAXTitleAttribute as String) as? String == what else { return false }
        pressed = AXUIElementPerformAction(element, kAXPressAction as CFString) == .success
        return true
    }
    exit(pressed ? 0 : 1)
default:
    exit(2)
}
