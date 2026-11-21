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
                if !driving {
                    Spacer(minLength: 0)
                    side("Type", typing ? "keyboard.chevron.compact.down" : "keyboard", on: typing, action: type)
                        .accessibilityIdentifier("typeButton")
                }
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity)
            micButton
            HStack(spacing: 0) {
                Spacer(minLength: 0)
                side("Sessions", "rectangle.stack", action: sessions).accessibilityIdentifier("sessionsButton")
                Spacer(minLength: 0)
                if live {
                    side("Hang up", "phone.down.fill", tint: Brand.dangerText, action: hangUp).accessibilityIdentifier("hangUp")
                } else {
                    side("Hang up", "phone.down.fill", action: {}).hidden().accessibilityHidden(true)
                }
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
    @ViewBuilder var cards: Cards
    @ViewBuilder var bar: Bar
    @State private var barHeight: CGFloat = 0

    var body: some View {
        VStack(spacing: 10) {
            FitScroll(limit: limit - barHeight - 10) {
                VStack(spacing: 10) { cards }.padding(1)  // a card's hairline is on its edge: keep it inside what is clipped
                    .environment(\.dockRoom, limit - barHeight - 10)
            }
            .padding(-1)
            VStack(spacing: 10) { bar }
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { barHeight = $0 }
        }
    }
}

/// Typed instead of spoken: for a noisy room or a quiet one.
struct TypeBar: View {
    var prompt = "Type to Pointe"
    let send: (String) async -> Bool
    let close: () -> Void
    @State private var text = ""
    @State private var sending = false
    @FocusState private var focused: Bool

    var body: some View {
        HStack(spacing: 10) {
            TextField(prompt, text: $text, axis: .vertical)
                .lineLimit(1...4)
                .focused($focused)
                .accessibilityIdentifier("typeField")
                .submitLabel(.send)
                .onSubmit(submit)
                .onChange(of: text) {  // a multi-line field takes Return as a new line: Return sends, as the key says
                    if text.hasSuffix("\n") { text.removeLast(); submit() }
                }
                .padding(.horizontal, 14).padding(.vertical, 10)
                .background(Brand.raised, in: RoundedRectangle(cornerRadius: 12))
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

    private var empty: Bool { text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    private func submit() {
        guard !empty else { return }
        let words = text.trimmingCharacters(in: .whitespacesAndNewlines)
        sending = true
        Task {
            if await send(words) { text = "" }
            sending = false
        }
    }
}
