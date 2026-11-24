import SwiftUI

/// The call's controls, at your thumb: the mic in the exact middle in every state, two controls either side (brain dump
/// and the keyboard; sessions and hang up). A control that comes and goes (the keyboard while driving) never moves the
/// mic: each side is half of what the mic leaves. Drive mode is a mode, like a meeting: its switch is in the header.
struct BottomBar: View {
    let phase: Call.State
    let muted: Bool
    let dump: API.BrainDump?  // dumping, in review, or none: the button reads Done, Review or Brain dump
    let typing: Bool
    let mic: () -> Void
    let listen: () -> Void
    let type: () -> Void
    let sessions: () -> Void
    let hangUp: () -> Void
    var talk: RingTalk? = nil  // push to talk: hold the ring
    var trace = ""             // debug builds: the last press, for the UI tests
    var driving = false        // drive mode: typing folds away

    private var live: Bool { phase == .live || phase == .reconnecting }

    var body: some View {
        HStack(spacing: 0) {
            HStack(spacing: 0) {
                Spacer(minLength: 0)
                side(BrainDumpCopy.buttonLabel(dump), dump == nil ? "brain.head.profile" : dump!.isDumping ? "checkmark.circle.fill" : "doc.text.magnifyingglass",
                     on: dump != nil, action: listen)
                    .disabled(!live)
                    .accessibilityIdentifier("dumpButton")
                Spacer(minLength: 0)
                if !driving {
                    side("Type", typing ? "keyboard.chevron.compact.down" : "keyboard", on: typing, action: type)
                        .disabled(!live && !typing)  // typing needs the call (Connect says so): a field it could not send from took text
                        .accessibilityIdentifier("typeButton")
                } else {  // its slot stays, empty, so Brain dump is where the thumb knows it
                    side("Type", "keyboard", action: {}).hidden().accessibilityHidden(true)
                }
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity)
            micButton
            HStack(spacing: 0) {
                Spacer(minLength: 0)
                side("Sessions", "rectangle.stack", action: sessions).accessibilityIdentifier("sessionsButton")
                Spacer(minLength: 0)
                // With no call Hang up shows, dimmed, as the mic does: hidden, it left the bar lopsided beside Brain dump and Type.
                side("Hang up", "phone.down.fill", tint: live ? Brand.dangerText : .primary, action: hangUp)
                    .disabled(!live)
                    .accessibilityIdentifier(live ? "hangUp" : "hangUpOff")  // the UI tests read "hangUp" as the call being up
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity)
        }
        .frame(maxWidth: Surface.isMac ? 560 : .infinity)  // in a wide window the controls stay together, as on the page
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .brandCard()
        .dynamicTypeSize(...DynamicTypeSize.large)  // five controls share one row: past this the labels push each other off; hold one for the large view
        .sensoryFeedback(.impact(weight: .medium), trigger: muted)
        .sensoryFeedback(.impact(weight: .light), trigger: dump?.state)
    }

    private var hot: Bool { phase == .live && (talk?.talking ?? !muted) }

    /// The mic is a mic: mute and unmute, or hold to talk. With no call it reads disabled and points at Connect.
    private var micButton: some View {
        Button(action: mic) {
            ZStack {
                Circle().fill(hot ? Brand.orange : Brand.raised)
                    .overlay(Circle().stroke(hot ? Color.clear : phase == .live ? Brand.orange : Brand.line, lineWidth: phase == .live ? 2 : 1))
                Image(systemName: hot ? "mic.fill" : phase == .live ? "mic.slash.fill" : "mic")
                    .font(.system(size: 26, weight: .semibold))
                    .foregroundStyle(hot ? Brand.onOrange : phase == .live ? Brand.accent : Brand.dim)
                    .contentTransition(.symbolEffect(.replace))
                if phase == .connecting || phase == .reconnecting { ProgressView().tint(Brand.muted).offset(y: 30) }
            }
            .frame(width: 70, height: 70)
        }
        .buttonStyle(.plain)
        .hoverLift()
        .disabled(phase != .live)
        .accessibilityIdentifier("micRing")
        .accessibilityValue(trace)
        .accessibilityLabel(phase == .live ? (muted ? "Unmute" : "Mute") : phase == .off ? "Microphone" : "Connecting")
        .accessibilityHint(phase == .off ? ConnectCopy.connectFirst : "")
        .ringTalk(phase == .live ? talk : nil)
    }

    private func side(_ label: String, _ symbol: String, on: Bool = false, tint: Color = .primary,
                      action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: 4) {
                Image(systemName: symbol).font(.system(size: 19, weight: .medium))
                    .frame(width: 46, height: 46)
                    .background(on ? AnyShapeStyle(Brand.tint) : AnyShapeStyle(Brand.raised), in: Circle())
                    .contentTransition(.symbolEffect(.replace))
                Text(label).font(.brand(.caption2)).lineLimit(1).fixedSize()
            }
            .foregroundStyle(tint)
        }
        .buttonStyle(.plain)
        .hoverLift()
        .accessibilityLabel(label)
        .largeContent { Label(label, systemImage: symbol) }
    }
}

/// The Microphone setting at hand, above the mic, as on the page: Always on, or push to talk in this phone's talk style.
/// The same setting as in Settings; the Mac keeps it, so the page and the app agree.
struct MicModeSwitch: View {
    let mode: String
    let style: TalkStyle
    let set: (String) -> Void

    var body: some View {
        Segments(selection: Binding(get: { mode }, set: set), options: [("always", "Always on"), ("ptt", style.label)]) {
        Picker("Microphone", selection: Binding(get: { mode }, set: set)) {
            Text("Always on").tag("always")
            Text(style.label).tag("ptt")
        }
        .pickerStyle(.segmented)
        }
        .fixedSize()
        .dynamicTypeSize(...DynamicTypeSize.xLarge)  // chrome over the bar: past this it crowds the cards above it
        .accessibilityIdentifier("micModeSwitch")
    }
}

/// What sits under a call: the cards that need you over the bar. The cards take what they need; when the keyboard, a
/// small screen or large type leaves less than that, they scroll inside the dock and the bar stays whole.
extension EnvironmentValues {
    /// The height the dock leaves its cards above the bar: a card that would not fit can fold itself.
    @Entry var dockRoom: CGFloat = .infinity
}

struct Dock<Cards: View, Bar: View>: View {
    var limit: CGFloat = .infinity
    /// Where the cards rest when they must scroll: on their bottom, where a card's answer buttons are.
    var anchor: UnitPoint = .bottom
    @ViewBuilder var cards: Cards
    @ViewBuilder var bar: Bar
    @State private var barHeight: CGFloat = 0

    var body: some View {
        VStack(spacing: 10) {
            FitScroll(limit: limit - barHeight - 10, anchor: anchor) {
                VStack(spacing: 10) { cards }.padding(1)  // a card's hairline is on its edge: keep it inside what is clipped
                    .environment(\.dockRoom, limit - barHeight - 10)
            }
            .padding(-1)
            VStack(spacing: 10) { bar }
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { barHeight = $0 }
        }
    }
}

/// A card in the dock whose answer must stay on screen (Start shift, Start, Ask and Dismiss): what is above the buttons
/// scrolls inside the card when the dock is short (a small window, a small phone, large type), as the approval card's does.
/// The buttons' own height is measured apart from what scrolls, so the limit never feeds back on itself.
struct AnswersInView<Above: View, Answers: View>: View {
    var spacing: CGFloat = 12
    var padding: CGFloat = 16
    @ViewBuilder var above: Above
    @ViewBuilder var answers: Answers
    @Environment(\.dockRoom) private var room
    @State private var answersHeight: CGFloat = 0

    private var aboveRoom: CGFloat {
        guard room.isFinite, answersHeight > 0 else { return .infinity }
        return max(56, room - answersHeight - spacing - padding * 2 - 2)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: spacing) {
            FitScroll(limit: aboveRoom) {
                VStack(alignment: .leading, spacing: spacing) { above }.frame(maxWidth: .infinity, alignment: .leading)
            }
            VStack(alignment: .leading, spacing: spacing) { answers }
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { answersHeight = $0 }
        }
        .padding(padding)
    }
}

/// The composer's rules, apart from the view so they are tested: Return sends; a new line is Shift+Return or Option+Return
/// on a keyboard (the Mac, an iPad's), and the New line key on the iPhone. Line breaks reach the Mac as typed.
enum Composer {
    enum Key: Equatable { case send, newLine }
    enum Change: Equatable { case keep, send(String) }

    static let newLineLabel = "New line"

    /// Return on a keyboard: with Shift or Option it writes a new line, alone it sends (as on the page).
    static func returnKey(shift: Bool, option: Bool) -> Key { shift || option ? .newLine : .send }

    /// The New line key: "\n" where the cursor is (replacing a selection), or at the end when the field has no cursor.
    static func newLine(in text: String, at selection: Range<String.Index>?) -> (text: String, cursor: String.Index) {
        guard let selection, selection.lowerBound >= text.startIndex, selection.upperBound <= text.endIndex else {
            let out = text + "\n"
            return (out, out.endIndex)
        }
        var out = text
        out.replaceSubrange(selection, with: "\n")
        let cursor = out.index(out.startIndex, offsetBy: text.distance(from: text.startIndex, to: selection.lowerBound) + 1)
        return (out, cursor)
    }

    /// A change the field made: a multi-line field takes the soft keyboard's Return as "\n", and Return sends. One "\n"
    /// added and nothing else is Return (anywhere in the line), unless it is the New line key's own (`expected`). Typing,
    /// pasting several lines and deleting are kept.
    static func fieldChanged(old: String, new: String, expected: String?) -> Change {
        if new == expected { return .keep }
        guard new.count == old.count + 1 else { return .keep }
        var a = old.startIndex, b = new.startIndex
        while a < old.endIndex, old[a] == new[b] { a = old.index(after: a); b = new.index(after: b) }
        guard new[b] == "\n", old[a...] == new[new.index(after: b)...] else { return .keep }
        return .send(old)
    }

    /// What is sent: the ends trimmed, the lines inside kept. Nil when there is nothing to send.
    static func sendable(_ text: String) -> String? {
        let words = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return words.isEmpty ? nil : words
    }
}

/// Typed instead of spoken: for a noisy room or a quiet one.
struct TypeBar: View {
    var prompt = "Type to Pointe"
    let send: (String) async -> Bool
    let close: () -> Void
    @State private var text = ""
    @State private var selection: TextSelection?
    @State private var expected: String?  // the New line key's own text: its "\n" is not a Return
    @State private var sending = false
    @FocusState private var focused: Bool

    var body: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField(prompt, text: $text, selection: $selection, axis: .vertical)
                .lineLimit(1...6)
                .focused($focused)
                .accessibilityIdentifier("typeField")
                .submitLabel(.send)
                .onSubmit(submit)
                .onKeyPress(.escape) { close(); return .handled }  // a hardware keyboard's Esc closes it, as Return sends
                .onKeyPress(.return, phases: .down) { press in  // a keyboard: Shift or Option + Return is a new line
                    switch Composer.returnKey(shift: press.modifiers.contains(.shift), option: press.modifiers.contains(.option)) {
                    case .newLine: newLine()
                    case .send: submit()
                    }
                    return .handled
                }
                .onChange(of: text) { old, new in  // the soft keyboard's Return writes "\n" into a multi-line field: it sends
                    if case .send(let before) = Composer.fieldChanged(old: old, new: new, expected: expected) {
                        text = before
                        submit()
                    }
                    if new == expected { expected = nil }
                }
                .padding(.horizontal, 14).padding(.vertical, 10)
                .background(Brand.raised, in: RoundedRectangle(cornerRadius: 12))
            #if os(iOS)  // the soft keyboard's Return sends: this key is the new line, beside the field like the send button
            Button(action: newLine) {
                Label(Composer.newLineLabel, systemImage: "return.left")
                    .labelStyle(.titleAndIcon)
                    .font(.brand(.footnote, .semibold)).foregroundStyle(Brand.muted)
                    .frame(height: 38).padding(.horizontal, 10)
                    .background(Brand.raised, in: Capsule())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("composerNewLine")
            #endif
            Button(action: submit) {
                Image(systemName: "arrow.up").font(.brand(.body, .semibold)).foregroundStyle(empty ? Brand.dim : Brand.onPrimary)
                    .frame(width: 38, height: 38)
                    .background(empty ? Brand.raised2 : Brand.primary, in: Circle())
                    .touchTarget(width: 38, height: 38)
            }
            .disabled(empty || sending)
            .accessibilityLabel("Send")
            .accessibilityIdentifier("typeSend")
        }
        .onAppear { focused = true }
    }

    private var empty: Bool { Composer.sendable(text) == nil }

    private func newLine() {
        var at: Range<String.Index>?
        if case .selection(let range) = selection?.indices { at = range }
        let out = Composer.newLine(in: text, at: at)
        expected = out.text
        text = out.text
        selection = TextSelection(insertionPoint: out.cursor)
        focused = true
    }

    private func submit() {
        guard let words = Composer.sendable(text) else { return }
        sending = true
        Task {
            if await send(words) { text = "" }
            sending = false
        }
    }
}
