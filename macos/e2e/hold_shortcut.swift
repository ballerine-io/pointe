import CoreGraphics
import Foundation
// Post ⌃⌥Space down, hold, up: a realistic hold for the hot key. Needs the Post Event (Accessibility) permission.
let ms = Double(CommandLine.arguments.dropFirst().first ?? "600") ?? 600
let src = CGEventSource(stateID: .hidSystemState)
func key(_ code: CGKeyCode, _ down: Bool, _ flags: CGEventFlags) { let e = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: down); e?.flags = flags; e?.post(tap: .cghidEventTap) }
print("trusted:", CGPreflightPostEventAccess())
key(49, true, [.maskControl, .maskAlternate])
var seen: [Bool] = []
let end = Date().addingTimeInterval(ms / 1000)
while Date() < end { seen.append(CGEventSource.keyState(.combinedSessionState, key: 49)); usleep(50_000) }
key(49, false, [.maskControl, .maskAlternate])
usleep(150_000)
print("keyState while held:", seen.map { $0 ? "1" : "0" }.joined(), "after:", CGEventSource.keyState(.combinedSessionState, key: 49))
