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
            window.contentMinSize = MainWindow.minSize
            window.isReleasedWhenClosed = false
            window.toolbarStyle = .unified
            // The window's size is the person's: the conversation's own ideal height (all of it) must not set it.
            let root = MainWindow().environment(AppModel.shared)
                .frame(minWidth: MainWindow.minSize.width, idealWidth: 820, maxWidth: .infinity, minHeight: MainWindow.minSize.height, idealHeight: 640, maxHeight: .infinity)
            let content = NSHostingView(rootView: root)
            content.sizingOptions = [.minSize]
            window.contentView = content
            window.setContentSize(NSSize(width: 820, height: 640))
            window.center()
            if Self.keepsFrames { window.setFrameAutosaveName("pointe.main") }
            window.delegate = self
            main = window
            for (name, up) in [(NSWindow.willBeginSheetNotification, true), (NSWindow.didEndSheetNotification, false)] {
                observers.append(NotificationCenter.default.addObserver(forName: name, object: window, queue: .main) { _ in
                    MainActor.assumeIsolated { AppModel.shared.sheetUp = up }
                })
            }
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

    private var dragStart: (mouse: NSPoint, origin: NSPoint)?

    /// A small panel that floats over other apps and never takes the keyboard from them. `small`: the pill.
    func setBubble(_ on: Bool, small: Bool = false) {
        guard on else { bubble?.orderOut(nil); return }
        let size = small ? BubbleRule.small : BubbleRule.full
        if bubble == nil {
            let panel = Self.bubblePanel(BubbleView().environment(AppModel.shared)) { inside in
                let model = AppModel.shared
                model.bubbleExpanded = inside && model.bubbleSmall
            }
            let screens = NSScreen.screens.map(\.visibleFrame)
            if !panel.setFrameUsingName("pointe.bubble") || !BubbleRule.reachable(panel.frame, screens: screens), let screen = NSScreen.main {
                panel.setFrameOrigin(BubbleRule.home(size: panel.frame.size, in: screen.visibleFrame))
            }
            if Self.keepsFrames { panel.setFrameAutosaveName("pointe.bubble") }
            bubble = panel
        }
        if let bubble, bubble.frame.size != size {
            let screen = (bubble.screen ?? NSScreen.main)?.visibleFrame ?? bubble.frame
            bubble.setFrame(BubbleRule.resized(bubble.frame, to: size, in: screen), display: true)
        }
        bubble?.orderFrontRegardless()
    }

    /// The panel itself. Dragging is the view's (`dragBubble`), not the window background's: AppKit's background drag
    /// takes the mouse down, so a click on the bubble could never be told from a drag.
    static func bubblePanel<Content: View>(_ view: Content, hovered: @escaping (Bool) -> Void = { _ in }) -> NSPanel {
        let panel = NSPanel(contentRect: NSRect(origin: .zero, size: BubbleRule.full),
                            styleMask: [.nonactivatingPanel, .borderless, .fullSizeContentView], backing: .buffered, defer: false)
        panel.identifier = NSUserInterfaceItemIdentifier("pointe.bubble")
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isMovableByWindowBackground = false
        panel.hidesOnDeactivate = false
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = true
        panel.title = "Pointe call bubble"
        let content = BubbleHost(rootView: view)
        content.hovered = hovered
        content.sizingOptions = []
        panel.contentView = content
        panel.setContentSize(BubbleRule.full)
        return panel
    }

    /// Follows the mouse from where the drag began, on the screen's coordinates: the view moves with the panel, so its
    /// own coordinates would chase themselves after the first step. `moved`: the view's translation, read only at that
    /// first step (screen y grows upward). The place is kept by the frame's autosave name.
    func dragBubble(moved: CGSize, ended: Bool) {
        guard let bubble else { return }
        let mouse = NSEvent.mouseLocation
        let start = dragStart ?? (NSPoint(x: mouse.x - moved.width, y: mouse.y + moved.height), bubble.frame.origin)
        dragStart = ended ? nil : start
        bubble.setFrameOrigin(NSPoint(x: start.origin.x + mouse.x - start.mouse.x, y: start.origin.y + mouse.y - start.mouse.y))
    }

    func resetBubblePosition() {
        guard let bubble, let screen = bubble.screen ?? NSScreen.main else { return }
        bubble.setFrameOrigin(BubbleRule.home(size: bubble.frame.size, in: screen.visibleFrame))
    }
}
