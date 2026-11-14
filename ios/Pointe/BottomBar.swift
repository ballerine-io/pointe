import SwiftUI

/// The call's controls, at your thumb: the mic in the exact middle in every state, two controls either side (brainstorm
/// and the keyboard; sessions and hang up). A control that comes and goes (the keyboard while driving) never moves the
/// mic: each side is half of what the mic leaves. Drive mode is a mode, like a meeting: its switch is in the header.
struct BottomBar: View {
    let phase: Call.State
    let muted: Bool
    let monologue: Bool
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
                side(monologue ? "Back" : "Brainstorm", monologue ? "bubble.left.and.bubble.right.fill" : "brain.head.profile",
                     on: monologue, action: listen)
                    .disabled(!live)
                if !driving {
                    Spacer(minLength: 0)
                    side("Type", typing ? "keyboard.chevron.compact.down" : "keyboard", on: typing, action: type)
                }
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity)
            micButton
            HStack(spacing: 0) {
                Spacer(minLength: 0)
                side("Sessions", "rectangle.stack", action: sessions)
                Spacer(minLength: 0)
                if live {
                    side("Hang up", "phone.down.fill", tint: .red, action: hangUp).accessibilityIdentifier("hangUp")
                } else {
                    side("Hang up", "phone.down.fill", action: {}).hidden().accessibilityHidden(true)
                }
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 30))
        .sensoryFeedback(.impact(weight: .medium), trigger: muted)
        .sensoryFeedback(.impact(weight: .light), trigger: monologue)
    }

    private var hot: Bool { phase == .live && (talk?.talking ?? !muted) }

    /// The mic is a mic: mute and unmute, or hold to talk. With no call it reads disabled and points at Connect.
    private var micButton: some View {
        Button(action: mic) {
            ZStack {
                Circle().fill(hot ? AnyShapeStyle(Brand.orange.gradient) : AnyShapeStyle(Brand.card))
                    .overlay(Circle().stroke(.white.opacity(phase == .live ? 0 : 0.1)))
                Image(systemName: hot ? "mic.fill" : phase == .live ? "mic.slash.fill" : "mic")
                    .font(.system(size: 26, weight: .semibold))
                    .foregroundStyle(phase == .live ? AnyShapeStyle(.white) : AnyShapeStyle(.secondary))
                    .contentTransition(.symbolEffect(.replace))
                if phase == .connecting || phase == .reconnecting { ProgressView().tint(.white).offset(y: 30) }
            }
            .frame(width: 70, height: 70)
            .shadow(color: hot ? Brand.orange.opacity(0.5) : .clear, radius: 12)
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
                    .background(on ? AnyShapeStyle(Brand.orange.opacity(0.25)) : AnyShapeStyle(.thinMaterial), in: Circle())
                    .contentTransition(.symbolEffect(.replace))
                Text(label).font(.caption2).lineLimit(1).fixedSize()
            }
            .foregroundStyle(tint)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
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
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 20))
            Button(action: submit) {
                Image(systemName: "arrow.up").font(.body.bold()).foregroundStyle(.white)
                    .frame(width: 38, height: 38)
                    .background(empty ? AnyShapeStyle(Color.gray.opacity(0.4)) : AnyShapeStyle(Brand.orange.gradient), in: Circle())
            }
            .disabled(empty || sending)
            .accessibilityLabel("Send")
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
