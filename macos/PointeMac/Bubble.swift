import AppKit
import PointeKit
import PointeUI
import SwiftUI

/// The call bubble's rules, apart from its drawing, so the unit tests can read each one.
enum BubbleRule {
    /// On screen while a call is up or being placed. With no call only when the person pinned it ("Keep it on screen
    /// with no call"), and never while "Show the call bubble during calls" is off: a bubble that says "Not connected" for hours is
    /// clutter, not a control.
    static func shows(on: Bool, pinned: Bool, phase: MacSession.Phase) -> Bool { on && (pinned || phase != .off) }

    /// "Always on", or in push to talk the shortcut that talks from any app ("Hold ⌥Space"); "Push to talk" with no
    /// working shortcut.
    static func talkMode(pushToTalk: Bool, hold: Bool, shortcut: String?) -> String {
        guard pushToTalk else { return "Always on" }
        guard let shortcut else { return "Push to talk" }
        return "\(hold ? "Hold" : "Tap") \(shortcut)"
    }

    static func talkModeGlyph(pushToTalk: Bool) -> String { pushToTalk ? "hand.tap" : "waveform" }

    /// The second line: why the last call did not start, else what is being heard, else the session the voice talks to.
    /// Heard words keep their end (the newest words); a reason or a session's name keeps its start, so it reads.
    static func detail(problem: String?, phase: MacSession.Phase, hearing: String, session: String?) -> (text: String, keepsEnd: Bool, bad: Bool) {
        if phase == .off, let problem, !problem.isEmpty { return (problem, false, true) }
        if !hearing.isEmpty { return (hearing, true, false) }
        return (session ?? MacCopy.appName, false, false)
    }

    /// A call the person placed ended before it started, with a reason: the window opens on it, where Connect shows the
    /// reason and its fix. Nil while the call is still being placed.
    static func failedDial(phase: MacSession.Phase, problem: String?) -> Bool? {
        switch phase {
        case .connecting, .reconnecting: nil
        case .live: false
        case .off: problem?.isEmpty == false
        }
    }

    /// The panel's size, its two-point margin for the shadow included.
    static let full = NSSize(width: 264, height: 80)
    static let small = NSSize(width: 80, height: 44)

    /// The frame for a new size: the corner nearest the screen's edges stays put, so the bubble grows into the screen.
    static func resized(_ frame: NSRect, to size: NSSize, in screen: NSRect) -> NSRect {
        let x = frame.midX > screen.midX ? frame.maxX - size.width : frame.minX
        let y = frame.midY > screen.midY ? frame.maxY - size.height : frame.minY
        return NSRect(origin: NSPoint(x: x, y: y), size: size)
    }

    /// Where the bubble starts, and where Reset Position puts it: the top right of the screen, under the menu bar.
    static func home(size: NSSize, in screen: NSRect) -> NSPoint {
        NSPoint(x: screen.maxX - size.width - 20, y: screen.maxY - size.height - 32)
    }

    /// A remembered place is kept only while its middle is on a screen: a display that went away must not take the
    /// bubble with it.
    static func reachable(_ frame: NSRect, screens: [NSRect]) -> Bool {
        screens.contains { $0.contains(NSPoint(x: frame.midX, y: frame.midY)) }
    }
}

/// The bubble's view host. The panel never becomes key and the app is usually not active, so AppKit hands a click to
/// the view only if the view takes the first mouse; without this every click on the bubble was swallowed, Connect
/// included.
/// Hover is watched here too: SwiftUI's `onHover` never fires in a panel of an app that is not active.
final class BubbleHost<Content: View>: NSHostingView<Content> {
    var hovered: ((Bool) -> Void)?
    private var area: NSTrackingArea?

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let area { removeTrackingArea(area) }
        let watch = NSTrackingArea(rect: .zero, options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect], owner: self, userInfo: nil)
        addTrackingArea(watch)
        area = watch
    }

    override func mouseEntered(with event: NSEvent) {
        super.mouseEntered(with: event)
        if event.trackingArea === area { hovered?(true) }
    }

    override func mouseExited(with event: NSEvent) {
        super.mouseExited(with: event)
        if event.trackingArea === area { hovered?(false) }
    }
}

/// The call in a corner of the screen: the state, what is being heard or why the call did not start, the talk mode, a
/// talk button and who waits. Click it to open Pointe, drag it anywhere; − makes it small, × hides it. It floats over
/// other apps and never takes the keyboard from them.
struct BubbleView: View {
    @Environment(AppModel.self) private var model
    @State private var pressed = false

    var body: some View {
        let small = model.bubbleSmall && !model.bubbleExpanded
        // The panel's size is the window's to set (`Windows.setBubble`, which keeps the corner nearest the screen's
        // edge): content that sized the panel itself would grow it from its top left, off the screen.
        Group { if small { pill } else { card } }
            .padding(2)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 3)
                .onChanged { model.windows.dragBubble(moved: $0.translation, ended: false) }
                .onEnded { model.windows.dragBubble(moved: $0.translation, ended: true) }
                .exclusively(before: TapGesture().onEnded {
                    if small { model.bubbleExpanded = true } else { model.windows.showMain() }
                }))
            .contextMenu {
                Button("Open Pointe") { model.windows.showMain() }
                Toggle("Keep on Screen with No Call", isOn: Binding(get: { model.bubblePinned }, set: { model.bubblePinned = $0 }))
                Button(model.bubbleSmall ? "Full Size" : "Make Small") { model.bubbleSmall.toggle() }
                Button("Reset Position") { model.windows.resetBubblePosition() }
                Divider()
                Button("Hide the Bubble") { model.bubbleOn = false }
            }
            .accessibilityElement(children: .contain)
            .accessibilityLabel("Pointe call bubble")
            .accessibilityAction(named: "Open Pointe") { model.windows.showMain() }
            .accessibilityIdentifier(small ? "bubble.small" : "bubble")
    }

    private var card: some View {
        let session = model.session
        let detail = BubbleRule.detail(problem: session.callProblem, phase: session.phase, hearing: session.hearing, session: session.activeSession)
        return HStack(spacing: 10) {
            talkButton
            VStack(alignment: .leading, spacing: 1) {
                Text(session.stateTitle).font(PointeLook.font(.callout, .medium)).foregroundStyle(PointeLook.text).lineLimit(1)
                    .accessibilityIdentifier("bubble.state")
                Text(detail.text).font(PointeLook.font(.caption)).foregroundStyle(detail.bad ? PointeLook.accent : PointeLook.muted)
                    .lineLimit(1).truncationMode(detail.keepsEnd ? .head : .tail)
                    .help(detail.text)
                    .accessibilityIdentifier("bubble.detail")
                Label(model.talkMode, systemImage: BubbleRule.talkModeGlyph(pushToTalk: session.pushToTalk))
                    .font(PointeLook.font(.caption2)).foregroundStyle(PointeLook.dim).lineLimit(1)
                    .accessibilityIdentifier("bubble.mode")
            }
            Spacer(minLength: 0)
            VStack(alignment: .trailing, spacing: 6) {
                HStack(spacing: 2) {
                    control(model.bubbleSmall ? "arrow.up.left.and.arrow.down.right" : "minus",
                            help: model.bubbleSmall ? "Keep the bubble full size" : "Make the bubble small", id: "bubble.small.toggle") {
                        model.bubbleSmall.toggle()
                    }
                    control("xmark", help: "Hide the bubble (Show call bubble during calls, in the menu, brings it back)", id: "bubble.close") {
                        model.bubbleOn = false
                    }
                }
                if session.needCount > 0 {
                    Button { model.windows.showMain() } label: {
                        Text("\(session.needCount)").font(PointeLook.font(.caption, .semibold)).monospacedDigit()
                            .frame(minWidth: 20, minHeight: 20).foregroundStyle(PointeLook.onOrange).background(PointeLook.orange, in: Capsule())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(MacCopy.needYou(session.needCount))
                    .help(MacCopy.needYou(session.needCount))
                }
            }
        }
        .padding(.leading, 12).padding(.trailing, 6)
        .frame(width: BubbleRule.full.width - 4, height: BubbleRule.full.height - 4)
        .background(PointeLook.card, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(PointeLook.lineStrong))
    }

    /// Small: the state in its circle and the talk mode's glyph. Hover or click shows the whole bubble.
    private var pill: some View {
        let session = model.session
        return HStack(spacing: 6) {
            Image(systemName: glyph)
                .font(.system(size: 12, weight: .semibold))
                .frame(width: 28, height: 28)
                .foregroundStyle(session.talking ? PointeLook.onOrange : PointeLook.text)
                .background(session.talking ? PointeLook.orange : PointeLook.raised, in: Circle())
                .overlay(alignment: .topTrailing) {
                    if session.needCount > 0 { Circle().fill(PointeLook.orange).frame(width: 9, height: 9) }
                }
            Image(systemName: BubbleRule.talkModeGlyph(pushToTalk: session.pushToTalk))
                .font(.system(size: 12)).foregroundStyle(PointeLook.muted)
        }
        .frame(width: BubbleRule.small.width - 4, height: BubbleRule.small.height - 4)
        .background(PointeLook.card, in: Capsule())
        .overlay(Capsule().stroke(PointeLook.lineStrong))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(session.stateTitle), \(model.talkMode)\(session.needCount > 0 ? ", \(MacCopy.needYou(session.needCount))" : "")")
    }

    private var glyph: String {
        let session = model.session
        guard session.live else { return "phone.fill" }
        return session.pushToTalk ? (session.talking ? "mic.fill" : "mic") : (session.muted ? "mic.slash.fill" : "mic.fill")
    }

    private var talkButton: some View {
        let session = model.session
        let live = session.live, ptt = session.pushToTalk, open = session.talking
        return Image(systemName: glyph)
            .font(.system(size: 15, weight: .semibold))
            .frame(width: 36, height: 36)
            .foregroundStyle(open ? PointeLook.onOrange : PointeLook.text)
            .background(open ? PointeLook.orange : PointeLook.raised, in: Circle())
            .contentShape(Circle())
            .gesture(DragGesture(minimumDistance: 0)
                .onChanged { _ in
                    guard !pressed else { return }
                    pressed = true
                    if !live { Task { await model.toggleCall() } } else { session.talkDown() }
                }
                .onEnded { _ in
                    pressed = false
                    session.talkUp()
                })
            .accessibilityElement()
            .accessibilityAddTraits(.isButton)
            .accessibilityLabel(!live ? MacCopy.connect : ptt ? (open ? "Talking" : session.talkLabel) : (session.muted ? "Unmute" : "Mute"))
            .accessibilityAction {
                if !live { Task { await model.toggleCall() } } else { session.talkDown(); if session.holdToTalk { session.talkUp() } }
            }
            .accessibilityIdentifier("bubble.talk")
    }

    private func control(_ symbol: String, help: String, id: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 9, weight: .bold)).foregroundStyle(PointeLook.muted)
                .frame(width: 18, height: 18).contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(help)
        .accessibilityLabel(help)
        .accessibilityIdentifier(id)
    }
}
