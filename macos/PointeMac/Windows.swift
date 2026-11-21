import AppKit
import SwiftUI

/// The app's windows. With none open the app is an accessory (menu bar only, no Dock icon); while the main window or
/// Settings is open it is a regular app, with a menu bar and a place in ⌘-Tab.
@MainActor
final class Windows: NSObject, NSWindowDelegate {
    private var main: NSWindow?
    private var bubble: NSPanel?
    private var observers: [NSObjectProtocol] = []

    override init() {
        super.init()
        let center = NotificationCenter.default
        for name in [NSWindow.willCloseNotification, NSWindow.didBecomeKeyNotification] {
            observers.append(center.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                Task { @MainActor in self?.settlePolicy() }
            })
        }
    }

    /// A demo's or a test's window is not the person's: where it stood is not kept.
    private static var keepsFrames: Bool { !AppModel.shared.session.isDemo && !UserDefaults.standard.bool(forKey: "PointeOpenWindow") }

    var mainIsFront: Bool { NSApp.isActive && main?.isKeyWindow == true && main?.occlusionState.contains(.visible) == true }

    /// Space in the call window is the talk key, as on the page: in push to talk it holds (or taps) the talk button, in
    /// Always on it mutes. Never while typing, never with a sheet up, and only on a call; any other Space goes on to
    /// whatever has the keyboard. The monitor is the app's own: it sees this app's keys only.
    private var spaceMonitor: Any?
    private func watchSpace() {
        guard spaceMonitor == nil else { return }
        spaceMonitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .keyUp]) { [weak self] event in
            guard event.keyCode == 49, event.modifierFlags.intersection([.command, .option, .control, .shift]).isEmpty else { return event }
            let (up, again, number) = (event.type == .keyUp, event.type == .keyDown && event.isARepeat, event.windowNumber)
            let taken = MainActor.assumeIsolated { self?.space(up: up, again: again, window: number) ?? false }  // a local monitor runs on the main thread
            return taken ? nil : event
        }
    }

    /// True when the key was the talk key and goes no further.
    private func space(up: Bool, again: Bool, window number: Int) -> Bool {
        guard let window = main, window.windowNumber == number, window.attachedSheet == nil, !(window.firstResponder is NSText) else { return false }
        let session = AppModel.shared.session
        if up { session.talkUp(); return false }
        if again { return session.live }
        return session.talkDown()
    }

    func activate() {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }

    func showMain() {
        if main == nil {
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 820, height: 640),
                                  styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                                  backing: .buffered, defer: false)
            window.title = "Pointe"
            window.titlebarAppearsTransparent = true  // the brand's own header is the top of the window
            window.titleVisibility = .hidden
            window.identifier = NSUserInterfaceItemIdentifier("pointe.main")
            window.contentMinSize = NSSize(width: 420, height: 480)
            window.isReleasedWhenClosed = false
            window.toolbarStyle = .unified
            // The window's size is the person's: the conversation's own ideal height (all of it) must not set it.
            let root = MainWindow().environment(AppModel.shared)
                .frame(minWidth: 420, idealWidth: 820, maxWidth: .infinity, minHeight: 480, idealHeight: 640, maxHeight: .infinity)
            let content = NSHostingView(rootView: root)
            content.sizingOptions = [.minSize]
            window.contentView = content
            window.setContentSize(NSSize(width: 820, height: 640))
            window.center()
            if Self.keepsFrames { window.setFrameAutosaveName("pointe.main") }
            window.delegate = self
            main = window
            watchSpace()
        }
        activate()
        main?.makeKeyAndOrderFront(nil)
    }

    /// Back to the menu bar once nothing but the bubble is on screen. Checked after the close has happened.
    private func settlePolicy() {
        DispatchQueue.main.async {
            let open = NSApp.windows.contains { $0.isVisible && $0.canBecomeMain && !($0 is NSPanel) }
            if !open, NSApp.activationPolicy() != .accessory { NSApp.setActivationPolicy(.accessory) }
        }
    }

    // MARK: the call bubble

    /// A small panel that floats over other apps and never takes the keyboard from them.
    func setBubble(_ on: Bool) {
        guard on else { bubble?.orderOut(nil); return }
        if bubble == nil {
            let panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 260, height: 64),
                                styleMask: [.nonactivatingPanel, .borderless, .fullSizeContentView], backing: .buffered, defer: false)
            panel.identifier = NSUserInterfaceItemIdentifier("pointe.bubble")
            panel.isFloatingPanel = true
            panel.level = .floating
            panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
            panel.isMovableByWindowBackground = true
            panel.hidesOnDeactivate = false
            panel.backgroundColor = .clear
            panel.isOpaque = false
            panel.hasShadow = true
            panel.title = "Pointe call bubble"
            let content = NSHostingView(rootView: BubbleView().environment(AppModel.shared))
            content.sizingOptions = []
            panel.contentView = content
            panel.setContentSize(NSSize(width: 264, height: 64))
            if !panel.setFrameUsingName("pointe.bubble"), let screen = NSScreen.main {
                let area = screen.visibleFrame
                panel.setFrameOrigin(NSPoint(x: area.maxX - 284, y: area.maxY - 96))
            }
            if Self.keepsFrames { panel.setFrameAutosaveName("pointe.bubble") }
            bubble = panel
        }
        bubble?.orderFrontRegardless()
    }
}
