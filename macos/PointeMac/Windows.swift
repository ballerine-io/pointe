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

    var mainIsFront: Bool { NSApp.isActive && main?.isKeyWindow == true && main?.occlusionState.contains(.visible) == true }

    func activate() {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }

    func showMain() {
        if main == nil {
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 820, height: 580),
                                  styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                                  backing: .buffered, defer: false)
            window.title = "Pointe"
            window.identifier = NSUserInterfaceItemIdentifier("pointe.main")
            window.contentMinSize = NSSize(width: 640, height: 420)
            window.isReleasedWhenClosed = false
            window.toolbarStyle = .unified
            // The window's size is the person's: the conversation's own ideal height (all of it) must not set it.
            let root = CallWindow().environment(AppModel.shared)
                .frame(minWidth: 640, idealWidth: 820, maxWidth: .infinity, minHeight: 420, idealHeight: 580, maxHeight: .infinity)
            let content = NSHostingView(rootView: root)
            content.sizingOptions = [.minSize]
            window.contentView = content
            window.setContentSize(NSSize(width: 820, height: 580))
            window.center()
            if AppModel.shared.stub == nil { window.setFrameAutosaveName("pointe.main") }  // a test's window is not the person's
            window.delegate = self
            main = window
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
            panel.setFrameAutosaveName("pointe.bubble")
            bubble = panel
        }
        bubble?.orderFrontRegardless()
    }
}
