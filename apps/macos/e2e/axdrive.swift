// Drives a running app through the Accessibility API, by the identifiers its views carry: for apps/macos/e2e/live.py, which
// runs the real app against a real daemon. XCUITest needs the owner to unlock Automation Mode each session; this needs
// only the Accessibility permission of the terminal that runs it.
//
//   axdrive <pid> press <id>            press the control
//   axdrive <pid> value <id>            print its value, title or label
//   axdrive <pid> label <id>            print its label (what VoiceOver reads), else its title or value
//   axdrive <pid> exists <id>           exit 0 when it is on screen
//   axdrive <pid> labelled <prefix>     print every label that starts with the prefix
//   axdrive <pid> count <id>            how many texts are inside it
//   axdrive <pid> texts <id>            print the texts inside it, one per line
//   axdrive <pid> window                print the id of the app's main window (for screencapture -l)
//   axdrive <pid> panel                 print the id of its floating panel (the call bubble)
//   axdrive <pid> button <title>        press the first button with this title (a system prompt's "Allow")
//   axdrive <pid> type <id> <text>      put text in a field and confirm it (Return)
//   axdrive <pid> set <id> <text>       put text in a field, nothing else
//   axdrive <pid> return <id> [shift|option]  focus the field and press Return in it, with that modifier (to this app only)
//   axdrive <pid> ids                   print every identifier on screen, for finding one
//   axdrive <pid> menu <title>          choose the menu bar item with this title (File ▸ New Session is "New Session")
//   axdrive <pid> size <width> <height> resize the main window
import ApplicationServices
import Foundation

let args = CommandLine.arguments
guard args.count >= 3, let pid = pid_t(args[1]) else {
    FileHandle.standardError.write(Data("usage: axdrive <pid> press|value|label|exists|labelled|count|window|panel|button|type|ids|menu|size [what]\n".utf8))
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
case "texts":
    guard let element = find(what) else { print("missing"); exit(1) }
    _ = walk(element) { inner in
        if attribute(inner, kAXRoleAttribute as String) as? String == kAXStaticTextRole as String { print(text(inner)) }
        return false
    }
case "window", "panel":
    let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
    let floating = Int(CGWindowLevelForKey(.floatingWindow))
    let mine = windows.filter { ($0[kCGWindowOwnerPID as String] as? pid_t) == pid && ($0[kCGWindowLayer as String] as? Int) == (args[2] == "panel" ? floating : 0) }
    guard let id = mine.first?[kCGWindowNumber as String] as? Int else { exit(1) }
    print(id)
case "type":
    let parts = what.split(separator: " ", maxSplits: 1).map(String.init)
    guard parts.count == 2, let element = find(parts[0]) else { print("missing"); exit(1) }
    AXUIElementSetAttributeValue(element, kAXFocusedAttribute as CFString, kCFBooleanTrue)
    guard AXUIElementSetAttributeValue(element, kAXValueAttribute as CFString, parts[1] as CFString) == .success else { exit(1) }
    exit(AXUIElementPerformAction(element, kAXConfirmAction as CFString) == .success ? 0 : 1)
case "set":
    let parts = what.split(separator: " ", maxSplits: 1).map(String.init)
    guard parts.count == 2, let element = find(parts[0]) else { print("missing"); exit(1) }
    AXUIElementSetAttributeValue(element, kAXFocusedAttribute as CFString, kCFBooleanTrue)
    let value = parts[1].replacingOccurrences(of: "\\n", with: "\n")
    exit(AXUIElementSetAttributeValue(element, kAXValueAttribute as CFString, value as CFString) == .success ? 0 : 1)
case "return":
    let parts = what.split(separator: " ").map(String.init)
    guard let id = parts.first, let element = find(id) else { print("missing"); exit(1) }
    AXUIElementSetAttributeValue(element, kAXFocusedAttribute as CFString, kCFBooleanTrue)
    let flags: CGEventFlags = parts.contains("shift") ? .maskShift : parts.contains("option") ? .maskAlternate : []
    for down in [true, false] {  // to this app's process only: nothing else on the Mac gets the key
        guard let event = CGEvent(keyboardEventSource: nil, virtualKey: 36, keyDown: down) else { exit(1) }
        event.flags = flags
        event.postToPid(pid)
        usleep(30_000)
    }
    exit(0)
case "ids":
    var seen = Set<String>()
    _ = walk(app) { element in
        if let id = attribute(element, kAXIdentifierAttribute as String) as? String, !id.isEmpty, !id.hasPrefix("_"), seen.insert(id).inserted { print(id) }
        return false
    }
case "menu":
    var chosen = false
    if let bar = attribute(app, kAXMenuBarAttribute as String) {
        _ = walk(bar as! AXUIElement) { element in
            guard attribute(element, kAXRoleAttribute as String) as? String == kAXMenuItemRole as String,
                  attribute(element, kAXTitleAttribute as String) as? String == what else { return false }
            chosen = AXUIElementPerformAction(element, kAXPressAction as CFString) == .success
            return true
        }
    }
    exit(chosen ? 0 : 1)
case "size":
    let parts = what.split(separator: " ").compactMap { Double($0) }
    guard parts.count == 2, let windows = attribute(app, kAXWindowsAttribute as String) as? [AXUIElement],
          let window = windows.first(where: { attribute($0, kAXSubroleAttribute as String) as? String == kAXStandardWindowSubrole as String }) else { exit(1) }
    var size = CGSize(width: parts[0], height: parts[1])
    guard let value = AXValueCreate(.cgSize, &size) else { exit(1) }
    exit(AXUIElementSetAttributeValue(window, kAXSizeAttribute as CFString, value) == .success ? 0 : 1)
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
